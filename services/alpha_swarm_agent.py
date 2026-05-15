"""alpha_swarm_agent.py -- AlphaSwarmComputeAgent extending BaseGroupService.

Per B+ architecture: one service, all alpha agents, extends BaseGroupService.
group_id="alpha", has_graduation=True

Plan 78-01 changes (D-01, D-04, D-08, D-35, D-36, D-37, D-38, POOL-FIX):
- Single LineageRecorder writes to topic_signal_lineage()
- Segment key built from hmm_regime numeric prefix + timeframe
- _LEAD_MAP: ES -> NQ lead resolution
- Volume profile stub removed; VolumeZscorePlugin (Plan 06) replaces it
- Pool comes from BaseGroupService._setup() only — no second pool

Plan 78-03 changes (D-05, D-06, D-07, D-23, D-24, D-25):
- _shadow_registry_ensure_swarm(): idempotent enrollment per-agent loop
- _graduation_loop(): 15-min Spearman evaluation of signal_lineage vs pnl_r
- _run_graduation_cycle(): iterates self._agents, per-(agent_id, timeframe) Spearman weight learning

Plan 80-07 changes:
- self._agents is list[BaseMultiplierAgent] with Skeptic, Correlation, RegimeCoherence, Counterfactual
- TF gate: SWARM_MIN_TF_MINUTES settings-driven (replaces frozenset lookup)
- No schema version gate — all signals from the pipeline are accepted
- Capacity semaphore: asyncio.Semaphore(SWARM_MAX_CONCURRENT_CALLS) — no timeout, Kafka lag-skip is the backpressure valve
- Weighted aggregation: _compute_final_multiplier normalized over non-error agents
- Shadow enrollment loops over self._agents
- Per-(agent_id, timeframe) Spearman weight learning via _evaluate_agent
- AlphaSwarmComputeAgent never writes UPDATE/INSERT signal_ledger directly
"""

from __future__ import annotations

import asyncio
import signal as _signal
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings
from src.core.ai.base_group_service import BaseGroupService
from src.core.ai.context import AIContext, Tier
from src.core.ai.lineage import LineageRecorder
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.output import AgentOutput
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import (
    topic_intelligence,
    topic_intelligence_i7_signals,
    topic_swarm_alpha,
)
from src.intelligence.ai.alpha.correlation_agent import CorrelationComputeAgent
from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualComputeAgent
from src.intelligence.ai.alpha.ml_scorer_agent import MLScorerMultiplierAgent
from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceComputeAgent
from src.intelligence.ai.alpha.skeptic_agent import SkepticComputeAgent
from src.intelligence.schemas import signal_dict_to_ranked
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION
from src.observability.metrics import (
    SWARM_AGENT_WEIGHT,
    SWARM_AGGREGATED_MULTIPLIER,
    SWARM_INVOCATIONS_TOTAL,
    SWARM_MULTIPLIER_DISTRIBUTION,
)

logger = structlog.get_logger(__name__)

# Graduation gate constants (D-24, D-25)
_GRAD_MIN_N = 100  # minimum resolved signals before Spearman is computed
_GRAD_DEMOTION_STREAK = 3  # consecutive negative-rho cycles to trigger demotion

# Agent-to-transform mapping for LineageRecorder attribution (D-22).
# Maps agent_id -> (transform_name, tier_level) for all four swarm agents.
_SWARM_AGENT_TO_TRANSFORM: dict[str, tuple[str, int]] = {
    "skeptic_v1": ("swarm_skeptic", 6),
    "correlation_v1": ("swarm_correlation", 6),
    "regime_coherence_v1": ("swarm_regime_coherence", 6),
    "counterfactual_v1": ("swarm_counterfactual", 6),
    "ml_scorer_v1": ("swarm_ml_scorer", 6),
}

# Lead index mapping: ES -> NQ (per D-36 / D-37)
# ES equities all route to NQ as the lead index.
# Any symbol NOT in this map is its own lead (self-lead default).
_LEAD_MAP: dict[str, str] = {"ES": "NQ"}

# TF name -> minutes mapping for SWARM_MIN_TF_MINUTES gate.
_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _resolve_lead(symbol: str) -> str:
    """Resolve the lead index for a given base symbol.

    Args:
        symbol: Base symbol (e.g. 'ES', 'NQ', 'CL')

    Returns:
        Lead base symbol. Returns symbol itself for unmapped symbols (self-lead).
    """
    return _LEAD_MAP.get(symbol, symbol)


def _now_utc_iso() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return format_iso_ts(datetime.now(UTC))


class AlphaSwarmComputeAgent(BaseGroupService):
    """Single service dispatching all alpha agents.

    Per D-32: extends BaseGroupService, one bar consumer, one signal consumer,
    one DB pool (from super()), one LineageRecorder, one LLMProviderChain, one AIContextCache.
    Agents are pure compute, iterated per signal via asyncio.gather().

    Plan 78-01: Write path is LineageRecorder -> topic_signal_lineage() -> LineageWriterAgent -> signal_lineage.
    Plan 80-07: self._agents is list[BaseMultiplierAgent]; no direct signal_ledger writes.
    """

    group_id = "alpha"
    has_graduation = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self.settings = settings
        self._lineage: LineageRecorder | None = None
        self._demotion_streak: int = 0  # consecutive negative-rho cycles (D-25)
        # Populated in _setup() after LLM chain is ready (CLAUDE.md pattern).
        self._agents: list[BaseMultiplierAgent] = []
        self._semaphore: asyncio.Semaphore | None = None
        # In-memory weights cache: (agent_id, timeframe) -> weight
        self._agent_weights: dict[tuple[str, str], float] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()

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
        """Intelligence topic carries IntelligenceEvent payloads for AIContextCache."""
        return [topic_intelligence(self.settings.env_name)]

    async def _setup(self) -> None:
        """Wire infrastructure beyond BaseGroupService defaults.

        POOL-FIX: pool is created once by super()._setup() in BaseGroupService.
        LineageRecorder gets the Kafka producer from self._producer (set by super).

        Plan 80-07: construct all four BaseMultiplierAgent instances + semaphore.
        """
        await super()._setup()

        # Agents require _llm_chain which is wired by super()._setup() — construct here.
        self._agents = [
            SkepticComputeAgent(llm_chain=self._llm_chain),
            CorrelationComputeAgent(llm_chain=self._llm_chain),
            RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
            CounterfactualComputeAgent(llm_chain=self._llm_chain),
        ]
        # MLScorerMultiplierAgent: no LLM chain; uses pool for ModelRegistry.
        # Must be appended after super()._setup() so self._pool is available.
        self._agents.append(MLScorerMultiplierAgent(pool=self._pool))
        await self._agents[-1]._setup_models()

        self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)

        # Single LineageRecorder for all swarm prediction events.
        # self._producer and self.env_name are set by BaseGroupService._setup()
        self._lineage = LineageRecorder(
            producer=self._producer,
            env_name=self.env_name,
        )
        await self._lineage.start()

        # D-23: idempotent enrollment — guarantees row exists even if migration missed
        if self._pool is not None:
            await self._shadow_registry_ensure_agents(self._agents)

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
        """Refresh agent.shadow_only from shadow_registry (registry is source of truth per D-07).

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
            if agent.agent_id in registry_state:
                agent.shadow_only = bool(registry_state[agent.agent_id])

    async def _graduation_loop(self) -> None:
        """Override BaseGroupService stub: evaluate all agents every 15 min.

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
            except Exception as exc:
                self.logger.error("graduation_cycle_failed", err=str(exc))

    async def _run_graduation_cycle(self) -> None:
        """Single evaluation cycle: per-agent Spearman weight learning + shadow refresh.

        Plan 80-07: iterates self._agents, calls _evaluate_agent for each.
        Reloads weights + refreshes shadow state at end.
        """
        for agent in self._agents:
            try:
                await self._evaluate_agent(agent.agent_id)
            except Exception as exc:
                self.logger.warning(
                    "alpha_swarm.graduation_failed",
                    agent_id=agent.agent_id,
                    error=str(exc),
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
                    rho_result = stats.spearmanr(multipliers, pnl_rs)
                    rho = (
                        float(rho_result.correlation) if rho_result.correlation is not None else 0.0
                    )
                except Exception:
                    rho = 0.0
                if rho != rho:  # NaN guard
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
                SWARM_AGENT_WEIGHT.labels(agent_id=agent_id, timeframe=tf).set(weight)

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
            if not t.cancelled() and (exc := t.exception()):
                self.logger.error("alpha_swarm.reload_ml_models_failed", error=str(exc))

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
                except Exception as exc:
                    self.logger.warning(
                        "alpha_swarm.model_reload_failed",
                        agent=agent.__class__.__name__,
                        error=str(exc),
                    )
        self.logger.info("alpha_swarm.ml_models_reloaded_sigusr1")

    async def _teardown(self) -> None:
        """Stop lineage recorder (drains buffer) before base teardown."""
        if self._lineage is not None:
            await self._lineage.stop()
        await super()._teardown()

    async def _handle_trigger(self, event: dict) -> None:
        """Unpack i7.signals envelope and dispatch each signal."""
        for raw_signal in event.get("signals", []):
            await self._process_one_signal(raw_signal)

    async def _process_one_signal(self, raw_signal: dict) -> None:
        """Process a single I7 ranked signal through all swarm agents.

        Plan 80-07 gates (in order, cheapest first):
        1. TF gate: timeframe_minutes < SWARM_MIN_TF_MINUTES -> skip
        2. Capacity gate: asyncio.Semaphore acquire (no timeout — Kafka lag-skip is the valve)
        3. Parallel asyncio.gather over self._agents
        4. Weighted aggregation -> aggregate event on topic_swarm_alpha
        """
        # Schema version gate — v0 signals have contaminated entry/zone data, skip entirely
        if raw_signal.get("signal_schema_version") != SIGNAL_SCHEMA_VERSION:
            return

        # TF gate — before any LLM context build (zero cost for ineligible signals)
        tf = raw_signal.get("tf") or raw_signal.get("timeframe", "")
        tf_minutes = _TF_MINUTES.get(tf, 0)
        if tf_minutes < self.settings.SWARM_MIN_TF_MINUTES:
            return

        try:
            signal = signal_dict_to_ranked(raw_signal)
        except Exception as e:
            self.logger.warning("alpha_swarm.invalid_trigger", signal=raw_signal, exc_info=e)
            return

        symbol = signal.symbol
        # Use tf from the parsed signal for consistency
        tf = signal.tf

        signal_id = signal.signal_id or uuid4()
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
            agents_with_context: list[BaseMultiplierAgent] = []
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
                SWARM_INVOCATIONS_TOTAL.labels(
                    agent_id=agent.agent_id, timeframe=tf, status="ok"
                ).inc()
                multiplier_val = result.payload.get("multiplier", 0.0)
                if isinstance(multiplier_val, (int, float)):
                    SWARM_MULTIPLIER_DISTRIBUTION.labels(agent_id=agent.agent_id).observe(
                        float(multiplier_val)
                    )
            else:
                err_str = (
                    str(result)
                    if isinstance(result, Exception)
                    else (result.error if isinstance(result, AgentOutput) else "unknown")
                )
                SWARM_INVOCATIONS_TOTAL.labels(
                    agent_id=agent.agent_id if not isinstance(result, Exception) else "unknown",
                    timeframe=tf,
                    status="error",
                ).inc()
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
            SWARM_INVOCATIONS_TOTAL.labels(agent_id="all", timeframe=tf, status="all_failed").inc()
            return

        SWARM_AGGREGATED_MULTIPLIER.labels(timeframe=tf).observe(final_multiplier)

        # Compute adjusted confidence
        original_confidence = signal_dict.get("calibrated_confidence") or signal_dict.get(
            "pre_quality_confidence", 0.5
        )
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

    async def _record_swarm_result(
        self,
        signal_id: Any,
        enriched: AIContext,
        agent: BaseMultiplierAgent,
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
        multiplier = None if is_error else result.payload.get("multiplier", 1.0)

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

    async def _enrich_context(self, ctx: AIContext) -> AIContext:
        """Pass-through (Phase 78 D-22).

        CorrelationAgent and VolumeAgent are deleted; their consumers (lead_context,
        volume_profile) no longer exist. Skeptic v2 reads volume_z_score and corr_z
        directly from AIContext via _render_full_context iterating model_fields.
        """
        return ctx


def main() -> None:
    settings = Settings()
    service = AlphaSwarmComputeAgent(settings)
    import asyncio

    asyncio.run(service.start())


if __name__ == "__main__":
    main()
