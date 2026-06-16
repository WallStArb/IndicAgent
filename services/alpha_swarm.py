"""alpha_swarm_agent.py -- AlphaSwarm extending BaseGroupCoordinator.

Per B+ architecture: one service, all alpha agents, extends BaseGroupCoordinator.
group_id="alpha". Graduation dispatch via override detection in BaseGroupCoordinator.

Plan 78-01 changes (D-01, D-04, D-08, D-35, D-36, D-37, D-38, POOL-FIX):
- Single LineageRecorder writes to topic_signal_lineage()
- Segment key built from hmm_regime numeric prefix + timeframe
- _LEAD_MAP: ES -> NQ lead resolution
- Volume profile stub removed; VolumeZscorePlugin (Plan 06) replaces it
- Pool comes from BaseGroupCoordinator._setup() only — no second pool

Plan 78-03 changes (D-05, D-06, D-07, D-23, D-24, D-25):
- _shadow_registry_ensure_swarm(): idempotent enrollment per-agent loop
- _graduation_loop(): 15-min Spearman evaluation of signal_lineage vs pnl_r
- _run_graduation_cycle(): iterates self._agents, per-(agent_id, timeframe) Spearman weight learning

Plan 80-07 changes:
- self._agents is list[Evaluator] with Skeptic, Correlation, RegimeCoherence, Counterfactual
- TF gate: SWARM_MIN_TF_MINUTES settings-driven (replaces frozenset lookup)
- No schema version gate — all signals from the pipeline are accepted
- Capacity semaphore: asyncio.Semaphore(SWARM_MAX_CONCURRENT_CALLS) — no timeout, Kafka lag-skip is the backpressure valve
- Weighted aggregation: _compute_final_multiplier normalized over non-error agents
- Shadow enrollment loops over self._agents
- Per-(agent_id, timeframe) Spearman weight learning via _evaluate_agent
- AlphaSwarm never writes UPDATE/INSERT signal_ledger directly
"""

from __future__ import annotations

import asyncio
import signal as _signal
import time
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings
from src.core.ai.evaluator import Evaluator
from src.core.ai.output import AgentOutput
from src.core.memory.factory import build_memory_client
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import (
    topic_intelligence,
    topic_intelligence_i7_signals,
    topic_swarm_alpha,
)

# MLEvaluator import retained for isinstance lookup in _setup
from src.intelligence.ai.alpha.ml_scorer_agent import MLEvaluator
from src.intelligence.ai.context import SignalContext, Tier
from src.intelligence.ai.group_coordinator import BaseGroupCoordinator
from src.intelligence.schemas import signal_dict_to_ranked
from src.observability.metrics import (
    SWARM_AGENT_WEIGHT,
    SWARM_AGGREGATED_MULTIPLIER,
    SWARM_DISPATCH_SECONDS,
    SWARM_INVOCATIONS_TOTAL,
    SWARM_MULTIPLIER_DISTRIBUTION,
)

logger = structlog.get_logger(__name__)

# Graduation gate constants (D-24, D-25)
_GRAD_MIN_N = 100  # minimum resolved signals before Spearman is computed
_GRAD_DEMOTION_STREAK = 3  # consecutive negative-rho cycles to trigger demotion

# TF name -> minutes mapping for SWARM_MIN_TF_MINUTES gate.
_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _now_utc_iso() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return format_iso_ts(datetime.now(UTC))


class AlphaSwarm(BaseGroupCoordinator):
    """Single service dispatching all alpha agents.

    Per D-32: extends BaseGroupCoordinator, one bar consumer, one signal consumer,
    one DB pool (from super()), one LineageRecorder, one LLMProviderChain, one SignalContextCache.
    Agents are pure compute, iterated per signal via asyncio.gather().

    Plan 78-01: Write path is LineageRecorder -> topic_signal_lineage() -> LineageWriter -> signal_lineage.
    Plan 80-07: self._agents is list[Evaluator]; no direct signal_ledger writes.
    """

    group_id = "alpha"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self.settings = settings
        self._demotion_streak: int = 0  # consecutive negative-rho cycles (D-25)
        # Populated in _setup() after LLM chain is ready (CLAUDE.md pattern).
        self._agents: list[Evaluator] = []
        self._semaphore: asyncio.Semaphore | None = None
        # Phase 097: MemoryClient built in _setup() behind AGENT_MEMORY_ENABLED gate.
        self._memory_client: Any | None = None
        # In-memory weights cache: (agent_id, timeframe) -> weight
        self._agent_weights: dict[tuple[str, str], float] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # Phase 109 Plan 05 Task 4: restrict config reload to ai.agent.* keys only.
        # (other prefixes like alert.lag.* are irrelevant to AlphaSwarm)
        self._config_prefixes = ("ai.agent.",)

    @property
    def agents(self) -> list:
        """List of agents managed by this group service."""
        return self._agents

    @property
    def trigger_topics(self) -> list[str]:
        """Kafka topics that trigger agent dispatch."""
        return [topic_intelligence_i7_signals(self.settings.env_name)]

    @property
    def output_topic(self) -> str:
        """Kafka topic for agent output fan-out."""
        return topic_swarm_alpha(self.settings.env_name)

    def _bar_topics(self) -> list[str]:
        """Intelligence topic carries IntelligenceEvent payloads for SignalContextCache."""
        return [topic_intelligence(self.settings.env_name)]

    async def _setup(self) -> None:
        """Wire infrastructure beyond BaseGroupCoordinator defaults.

        POOL-FIX: pool is created once by super()._setup() in BaseGroupCoordinator.
        LineageRecorder gets the Kafka producer from self._producer (set by super).

        Agents are now built by AgentRegistry in BaseGroupCoordinator._setup().
        This method only configures semaphore, config propagation, and SIGUSR1.
        """
        await super()._setup()

        # Phase 097: build MemoryClient behind AGENT_MEMORY_ENABLED gate.
        # Returns None when disabled (default) or on construction error — agents
        # gate on `if context.memory_client is not None` before reading.
        self._memory_client = build_memory_client(self.settings, self._pool)

        # Phase 097: inject the MemoryClient (or None when disabled) into every
        # agent so that context.memory_client is the live client at compute time.
        # set_memory_client() is a post-construction setter on BaseAIWorker (MEM-01).
        for agent in self._agents:
            if hasattr(agent, "set_memory_client"):
                agent.set_memory_client(self._memory_client)

        # MLEvaluator requires async _setup_models() call — find by type.
        ml = next((a for a in self._agents if isinstance(a, MLEvaluator)), None)
        if ml is not None:
            await ml._setup_models()

        self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)

        # Phase 109 Plan 05 Task 4: apply config-DB shadow_mode overrides BEFORE
        # shadow_registry sync. D-07 precedence: config DB wins when both sources exist.
        # Propagate ai.agent.* keys from AlphaSwarm's cache to each agent's cache so
        # agent._apply_shadow_mode_config() can read them via self.get_config().
        for agent in self._agents:
            for k, v in self._config_cache.items():
                if k.startswith("ai.agent."):
                    agent._config_cache[k] = v
            if hasattr(agent, "_apply_shadow_mode_config"):
                agent._apply_shadow_mode_config()

        # SIGUSR1 hot-reload: triggered by nightly training agent after model registration.
        # asyncio.get_running_loop() MUST be used here (not get_event_loop()) — this is
        # inside an async function so the running loop is guaranteed to be the right one
        # (Pitfall 5 in Phase 070 RESEARCH.md).
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)
        self.logger.info("alpha_swarm.sigusr1_handler_registered")

        agent_ids = [a.agent_id for a in self._agents]
        self.logger.info("alpha_swarm.started", agents=agent_ids)

    async def _refresh_shadow_state_from_registry(self) -> None:
        """Refresh agent.shadow_only from shadow_registry with D-07 precedence.

        D-07 precedence (Phase 109): config DB takes precedence over shadow_registry
        when a config entry exists for ai.agent.<agent_id>.shadow_mode. Only fall
        back to shadow_registry if no config entry exists for this agent.

        Called once per graduation cycle to propagate DB state to runtime agent flags.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT component_name, is_shadow FROM shadow_registry "
                "WHERE component_type = 'swarm_agent'"
            )
        registry_state = {r["component_name"]: r["is_shadow"] for r in rows}
        for agent in self._agents:
            # D-07: check config DB FIRST
            config_override = self.get_config(f"ai.agent.{agent.agent_id}.shadow_mode", None)
            if config_override is not None:
                # Config DB wins -- delegate to the agent's normalizer.
                if hasattr(agent, "_apply_shadow_mode_config"):
                    agent._apply_shadow_mode_config()
                continue
            # No config entry -- fall back to shadow_registry
            if agent.agent_id in registry_state:
                agent.shadow_only = bool(registry_state[agent.agent_id])

    async def _on_config_message_received(self, key: str, value: object) -> None:
        """Route ai.agent.*.shadow_mode config updates to the individual AI agents.

        Plan 03 mixin already updated self._config_cache before invoking this hook,
        so this method propagates the update to each agent's cache and then calls
        _apply_shadow_mode_config() to flip shadow_only if appropriate.

        Only processes keys starting with 'ai.agent.' (other keys are blocked by
        _config_prefixes before reaching this hook).
        """
        if key.startswith("ai.agent."):
            for agent in self._agents:
                # Propagate the updated key to each agent's cache so that
                # agent._apply_shadow_mode_config() can read it via self.get_config().
                agent._config_cache[key] = value
                if hasattr(agent, "_apply_shadow_mode_config"):
                    agent._apply_shadow_mode_config()

    async def _graduation_loop(self) -> None:
        """Override BaseGroupCoordinator stub: evaluate all agents every 15 min.

        Runs Spearman ρ on (multiplier vs pnl_r) per (agent_id, timeframe) from
        signal_lineage JOIN signal_ledger. UPSERTs swarm_agent_weights.
        D-05, D-06, D-07, D-08 (Plan 80-07).
        """
        interval_s: float = getattr(self.settings, "swarm_graduation_interval_s", 900)
        while self.running:
            try:
                await asyncio.sleep(interval_s)
                await self._run_graduation_cycle()
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.logger.error("graduation_cycle_failed", err=str(error))

    async def _run_graduation_cycle(self) -> None:
        """Single evaluation cycle: per-agent Spearman weight learning + shadow refresh.

        Plan 80-07: iterates self._agents, calls _evaluate_agent for each.
        Reloads weights + refreshes shadow state at end.
        """
        for agent in self._agents:
            try:
                await self._evaluate_agent(agent.agent_id)
            except Exception as error:
                self.logger.warning(
                    "alpha_swarm.graduation_failed",
                    agent_id=agent.agent_id,
                    error=str(error),
                )
        await self._reload_agent_weights()
        await self._refresh_shadow_state_from_registry()

    async def _evaluate_agent(self, agent_id: str) -> None:
        """Per-agent Spearman weight learning: query 30d lineage, UPSERT swarm_agent_weights.

        Per (agent_id, timeframe): computes weight = max(WEIGHT_FLOOR, 0.5 + spearman_rho).
        Skips if sample_size < SWARM_WEIGHT_MIN_SAMPLES.
        Updates Prometheus SWARM_AGENT_WEIGHT gauge after each upsert.
        T-78-08: malformed rows filtered. T-78-09: hard N gate.
        """
        assert self._pool is not None
        import scipy.stats as stats  # local import to avoid hard dep at module level

        # Single connection for both the SELECT and all INSERT/upsert operations.
        # Previously a second acquire() was called inside the per-tf loop, causing
        # 1 + N pool acquisitions per agent per cycle (N = distinct timeframes).
        # With 4 agents × 6 TFs that's 28 acquisitions per cycle — pool exhaustion
        # risk under concurrent graduation + signal processing load.
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sl.tf AS timeframe,
                       sl.multiplier AS multiplier,
                       (sl.metadata->'payload'->>'confidence')::float AS stated_confidence,
                       ledger.pnl_r AS pnl_r
                FROM signal_lineage sl
                JOIN signal_ledger ledger ON ledger.signal_id = sl.signal_id
                WHERE sl.event_type = 'agent_prediction'
                  AND sl.source = $1
                  AND sl.multiplier IS NOT NULL
                  AND ledger.outcome IS NOT NULL
                  AND ledger.pnl_r IS NOT NULL
                  AND sl.ts > NOW() - INTERVAL '30 days'
                """,
                agent_id,
            )
            if not rows:
                return

            by_tf: dict[str, list[dict]] = {}
            for r in rows:
                by_tf.setdefault(r["timeframe"], []).append(r)

            min_n = self.settings.SWARM_WEIGHT_MIN_SAMPLES
            floor = self.settings.SWARM_WEIGHT_FLOOR
            for tf, group in by_tf.items():
                n = len(group)
                if n < min_n:
                    continue
                multipliers = [g["multiplier"] for g in group]
                pnl_rs = [g["pnl_r"] for g in group]
                try:
                    rho = float(stats.spearmanr(multipliers, pnl_rs).statistic)
                except Exception as error:
                    self.logger.warning(
                        "graduation.spearman_failed",
                        agent_id=agent_id,
                        tf=tf,
                        n=n,
                        error=str(error),
                    )
                    rho = 0.0
                if rho != rho:  # NaN guard for constant inputs
                    rho = 0.0
                weight = max(floor, 0.5 + rho)

                stated = [
                    g["stated_confidence"] for g in group if g["stated_confidence"] is not None
                ]
                win_rate = sum(1 for g in group if (g["pnl_r"] or 0) > 0) / n
                cal_err = abs((sum(stated) / len(stated)) - win_rate) if stated else None

                await conn.execute(
                    """
                    INSERT INTO swarm_agent_weights
                        (agent_id, timeframe, weight, sample_size, spearman_rho, calibration_error, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (agent_id, timeframe) DO UPDATE SET
                        weight = EXCLUDED.weight,
                        sample_size = EXCLUDED.sample_size,
                        spearman_rho = EXCLUDED.spearman_rho,
                        calibration_error = EXCLUDED.calibration_error,
                        updated_at = NOW()
                    """,
                    agent_id,
                    tf,
                    weight,
                    n,
                    rho,
                    cal_err,
                )
                SWARM_AGENT_WEIGHT.set(weight, {"agent_id": agent_id, "timeframe": tf})

    async def _reload_agent_weights(self) -> None:
        """Reload self._agent_weights cache from swarm_agent_weights table.

        Renormalizes per-timeframe so per-tf weight-sum equals number of agents
        producing weights for that tf.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT agent_id, timeframe, weight FROM swarm_agent_weights")
        per_tf: dict[str, list[tuple[str, float]]] = {}
        for r in rows:
            per_tf.setdefault(r["timeframe"], []).append((r["agent_id"], float(r["weight"])))
        normalized: dict[tuple[str, str], float] = {}
        for tf, items in per_tf.items():
            total = sum(w for _, w in items)
            n = len(items)
            # SWARM_WEIGHT_FLOOR (default 0.05) guarantees total > 0 when items is non-empty.
            # If floor is ever set to 0.0, this branch silently falls back to default_w in dispatch.
            if total > 0:
                for aid, w in items:
                    normalized[(aid, tf)] = (w / total) * n
        self._agent_weights = normalized

    def _compute_final_multiplier(
        self,
        agents: list,
        results: list,
        tf: str,
    ) -> tuple[float | None, int]:
        """Compute normalized weighted average multiplier from non-error agent results.

        Returns (final_multiplier, valid_agent_count).
        Returns (None, 0) when all agents failed or produced no multiplier.
        Default weight when (agent_id, tf) absent from self._agent_weights is 1/N.
        """
        weighted_sum = 0.0
        weight_sum = 0.0
        valid_count = 0
        default_w = 1.0 / max(len(agents), 1)
        for agent, result in zip(agents, results):
            if isinstance(result, AgentOutput) and not result.error:
                m = result.payload.get("multiplier")
                if m is None:
                    continue
                w = self._agent_weights.get((agent.agent_id, tf), default_w)
                weighted_sum += w * m
                weight_sum += w
                valid_count += 1
        if weight_sum == 0.0 or valid_count == 0:
            return None, 0
        return weighted_sum / weight_sum, valid_count

    def _on_sigusr1(self) -> None:
        """Sync SIGUSR1 handler — schedules ML model hot-reload via asyncio task.

        Signal handlers must be synchronous; async work is scheduled via create_task.
        The task is stored in self._background_tasks to prevent GC before completion.
        """
        self.logger.info("alpha_swarm.sigusr1_received")
        task = asyncio.create_task(self._reload_ml_models())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        def _log_exc(t: asyncio.Task[Any]) -> None:
            if not t.cancelled() and (error := t.exception()):
                self.logger.error("alpha_swarm.reload_ml_models_failed", error=str(error))

        task.add_done_callback(_log_exc)

    async def _reload_ml_models(self) -> None:
        """Reload models on all agents that expose _setup_models() (SIGUSR1 trigger).

        Exceptions per-agent are caught and logged; one agent's reload failure
        does not abort the rest.
        """
        for agent in self._agents:
            if hasattr(agent, "_setup_models"):
                try:
                    await agent._setup_models()
                except Exception as error:
                    self.logger.warning(
                        "alpha_swarm.model_reload_failed",
                        agent=agent.__class__.__name__,
                        error=str(error),
                    )
        self.logger.info("alpha_swarm.ml_models_reloaded_sigusr1")

    async def _teardown(self) -> None:
        """Delegate to base teardown (lineage lifecycle owned by BaseGroupCoordinator)."""
        await super()._teardown()

    async def _handle_trigger(self, event: dict) -> None:
        """Unpack i7.signals envelope and dispatch each signal."""
        for raw_signal in event.get("signals", []):
            await self._process_one_signal(raw_signal)

    async def _process_one_signal(self, raw_signal: dict) -> None:
        """Process a single I7 ranked signal through all swarm agents.

        Plan 80-07 gates (in order, cheapest first):
        1. Schema version gate: skip v0 signals
        2. Source gate: skip backfill signals (no value in AI enrichment on historical bars)
        3. TF gate: timeframe_minutes < SWARM_MIN_TF_MINUTES -> skip
        4. Confidence gate: winner_confidence < SWARM_MIN_CONFIDENCE -> skip
        5. Capacity gate: asyncio.Semaphore acquire (no timeout — Kafka lag-skip is the valve)
        6. Parallel asyncio.gather over self._agents
        7. Weighted aggregation -> aggregate event on topic_swarm_alpha
        """
        # Source gate — backfill signals are historical; AI enrichment adds no value
        if raw_signal.get("source") == "backfill":
            return

        # TF gate — before any LLM context build (zero cost for ineligible signals)
        tf = raw_signal.get("tf") or raw_signal.get("timeframe", "")
        tf_minutes = _TF_MINUTES.get(tf, 0)
        if tf_minutes < self.settings.SWARM_MIN_TF_MINUTES:
            return

        # Confidence gate — skip low-quality signals to preserve LLM budget
        _conf = raw_signal.get("confidence")
        if _conf is None:
            _conf = raw_signal.get("pre_quality_confidence")
        signal_confidence = float(_conf) if _conf is not None else 0.0
        if signal_confidence < self.settings.SWARM_MIN_CONFIDENCE:
            return

        symbol = raw_signal.get("symbol", "")
        _dispatch_t0 = time.monotonic()

        try:
            signal = signal_dict_to_ranked(raw_signal)
        except Exception as e:
            self.logger.warning("alpha_swarm.invalid_trigger", signal=raw_signal, exc_info=e)
            return

        symbol = signal.symbol
        # Use tf from the parsed signal for consistency
        tf = signal.tf

        if not signal.signal_id:
            raise ValueError(
                f"alpha_swarm: signal missing signal_id — "
                f"setup_plugin={getattr(signal, 'setup_plugin', None)!r}"
            )
        signal_id = signal.signal_id
        signal_dict = signal.model_dump()

        # Build context for enrichment (SMC tier for hmm_regime segment_key)
        context = self._context_cache.build(
            symbol=symbol,
            tf=tf,
            tiers_needed=frozenset({Tier.SMC}),
            signal=signal_dict,
            signal_id=signal_id,
        )
        if context is None:
            self.logger.warning(
                "alpha_swarm.no_context",
                symbol=symbol,
                tf=tf,
            )
            return

        enriched = await self._enrich_context(context)

        # Capacity semaphore — block until a slot is free (D-07: never skip mid-process).
        assert self._semaphore is not None
        await self._semaphore.acquire()

        try:
            # Build per-agent contexts and run in parallel
            tasks = []
            agents_with_context: list[Evaluator] = []
            for agent in self._agents:
                agent_context = self._context_cache.build(
                    symbol=symbol,
                    tf=tf,
                    tiers_needed=agent.tiers_needed,
                    signal=signal_dict,
                    signal_id=signal_id,
                )
                if agent_context is None:
                    self.logger.warning(
                        "alpha_swarm.no_agent_context",
                        agent_id=agent.agent_id,
                        symbol=symbol,
                        tf=tf,
                    )
                    continue
                tasks.append(agent.compute(agent_context))
                agents_with_context.append(agent)

            if not tasks:
                return

            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._semaphore.release()

        # Per-agent invocation accounting + lineage emission
        for agent, result in zip(agents_with_context, results):
            if isinstance(result, AgentOutput) and not result.error:
                SWARM_INVOCATIONS_TOTAL.add(
                    1, {"agent_id": agent.agent_id, "timeframe": tf, "status": "ok"}
                )
                multiplier_val = result.payload.get("multiplier", 0.0)
                if isinstance(multiplier_val, (int, float)):
                    SWARM_MULTIPLIER_DISTRIBUTION.record(
                        float(multiplier_val), {"agent_id": agent.agent_id}
                    )
            else:
                err_str = (
                    str(result)
                    if isinstance(result, Exception)
                    else (result.error if isinstance(result, AgentOutput) else "unknown")
                )
                SWARM_INVOCATIONS_TOTAL.add(
                    1,
                    {
                        "agent_id": (
                            agent.agent_id if not isinstance(result, Exception) else "unknown"
                        ),
                        "timeframe": tf,
                        "status": "error",
                    },
                )
                self.logger.info(
                    "alpha_swarm.agent_error",
                    agent_id=agent.agent_id,
                    error=err_str,
                )

            # Lineage record for every result (including errors) — counterfactual preservation D-07
            await self._record_swarm_result(signal_id, enriched, agent, result)

        # Weighted aggregation
        final_multiplier, agent_count = self._compute_final_multiplier(
            agents_with_context, list(results), tf
        )

        if final_multiplier is None:
            SWARM_INVOCATIONS_TOTAL.add(
                1, {"agent_id": "all", "timeframe": tf, "status": "all_failed"}
            )
            return

        SWARM_AGGREGATED_MULTIPLIER.record(final_multiplier, {"timeframe": tf})

        # Compute adjusted confidence
        original_confidence = signal_dict.get("confidence")
        if original_confidence is None:
            original_confidence = signal_dict.get("pre_quality_confidence", 0.5)
        if not isinstance(original_confidence, (int, float)):
            original_confidence = 0.5
        adjusted_confidence = float(original_confidence) * final_multiplier

        # Build agent_outputs list for downstream writers (e.g. swarm_ledger_writer_agent
        # extracts ml_scorer_v1 payload to populate ml_score / ml_model_id).
        agent_outputs_list = []
        for agent, result in zip(agents_with_context, results):
            if isinstance(result, AgentOutput) and not result.error:
                agent_outputs_list.append(
                    {
                        "agent_id": agent.agent_id,
                        "payload": result.payload,
                    }
                )

        # Publish aggregate adjustment event (Plan 08's writer owns signal_ledger projection)
        event_payload = {
            "signal_id": str(signal_id),
            "symbol": enriched.symbol,
            "timeframe": tf,
            "swarm_multiplier": final_multiplier,
            "adjusted_confidence": adjusted_confidence,
            "swarm_agent_count": agent_count,
            "agent_outputs": agent_outputs_list,
            "ts": _now_utc_iso(),
        }
        await self._producer.publish(
            topic_swarm_alpha(self.settings.env_name),
            msg=event_payload,
        )

        self.logger.info(
            "alpha_swarm.aggregate_emitted",
            signal_id=str(signal_id),
            symbol=symbol,
            tf=tf,
            swarm_multiplier=round(final_multiplier, 4),
            agent_count=agent_count,
        )
        SWARM_DISPATCH_SECONDS.record(
            time.monotonic() - _dispatch_t0, {"symbol": symbol, "timeframe": tf}
        )

    async def _record_swarm_result(
        self,
        signal_id: Any,
        enriched: SignalContext,
        agent: Evaluator,
        result: Any,
    ) -> None:
        """Record swarm agent prediction via LineageRecorder -> topic_signal_lineage().

        Plan 80-07: per-agent lineage with future-compatible metadata fields including
        shadow_at_write, parse_status, prompt_version (D-07).
        Single write path to signal_lineage (D-01, D-04, D-08).
        """
        if self._lineage is None:
            return

        # Build segment_key from SMC hmm_regime (numeric) + timeframe.
        # When hmm_regime is None (HMM model not yet converged, e.g. session warm-up),
        # use a sentinel key rather than dropping the lineage record — D-07 requires
        # lineage for every result. Dropping records here excludes early-session bars
        # from the Spearman weight learning dataset, violating the "never drop data
        # that could contain signal" Renaissance principle.
        hmm_regime = enriched.smc.hmm_regime if enriched.smc is not None else None
        if hmm_regime is None:
            self.logger.warning(
                "alpha_swarm.missing_hmm_regime",
                kind="missing_hmm_regime",
                signal_id=str(signal_id),
                agent_id=agent.agent_id,
                symbol=enriched.symbol,
                tf=enriched.timeframe,
            )
            segment_key = f"unknown.{enriched.timeframe}"  # sentinel — HMM not yet converged
        else:
            segment_key = f"{int(hmm_regime)}.{enriched.timeframe}"
        is_error = not isinstance(result, AgentOutput) or bool(result.error)
        multiplier = None if is_error else result.payload.get("multiplier")

        self._lineage.record(
            signal_id=signal_id,
            event_type="agent_prediction",
            source=agent.agent_id,
            multiplier=multiplier,
            metadata={
                "agent_id": agent.agent_id,
                "segment_key": segment_key,
                "confidence": (
                    result.payload.get("confidence", 0.0)
                    if isinstance(result, AgentOutput)
                    else 0.0
                ),
                "group": agent.group,
                "prompt_version": (
                    result.payload.get("prompt_version")
                    if isinstance(result, AgentOutput)
                    else None
                ),
                "payload": (result.payload if isinstance(result, AgentOutput) else {}),
                "error": (result.error if isinstance(result, AgentOutput) else str(result)),
                "shadow_at_write": agent.shadow_only,
                "parse_status": "ok" if not is_error else "failed",
            },
            symbol=enriched.symbol,
            tf=enriched.timeframe,
        )

    async def _enrich_context(self, ctx: SignalContext) -> SignalContext:
        """Pass-through (Phase 78 D-22).

        CorrelationAgent and VolumeAgent are deleted; their consumers (lead_context,
        volume_profile) no longer exist. Skeptic v2 reads volume_z_score and corr_z
        directly from SignalContext via _render_full_context iterating model_fields.
        """
        return ctx


def main() -> None:
    settings = Settings()
    service = AlphaSwarm(settings)
    import asyncio

    asyncio.run(service.start())


if __name__ == "__main__":
    main()
