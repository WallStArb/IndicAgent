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
- _shadow_registry_ensure_swarm(): idempotent enrollment of skeptic_v1
- _graduation_loop(): 15-min Spearman evaluation of signal_lineage vs pnl_r
- _run_graduation_cycle(): single evaluation cycle (promotion/demotion gates)
"""

from __future__ import annotations

import asyncio
import math
from typing import Any
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog
from scipy.stats import spearmanr

from src.config.settings import Settings
from src.core.ai.base_group_service import BaseGroupService
from src.core.ai.context import AIContext
from src.core.ai.lineage import LineageRecorder
from src.core.ai.output import AgentOutput
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_swarm_alpha,
)
from src.intelligence.ai.alpha.correlation_agent import CorrelationAgentComputeAgent
from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent
from src.intelligence.ai.alpha.volume_agent import VolumeAgentComputeAgent
from src.intelligence.schemas import signal_dict_to_ranked

logger = structlog.get_logger(__name__)

_ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

# Graduation gate constants (D-24, D-25)
_GRAD_MIN_N = 100           # minimum resolved signals before Spearman is computed
_GRAD_DEMOTION_STREAK = 3   # consecutive negative-rho cycles to trigger demotion

# Lead index mapping: ES -> NQ (per D-36 / D-37)
# ES equities all route to NQ as the lead index.
# Any symbol NOT in this map is its own lead (self-lead default).
_LEAD_MAP: dict[str, str] = {"ES": "NQ"}


def _resolve_lead(symbol: str) -> str:
    """Resolve the lead index for a given base symbol.

    Args:
        symbol: Base symbol (e.g. 'ES', 'NQ', 'CL')

    Returns:
        Lead base symbol. Returns symbol itself for unmapped symbols (self-lead).
    """
    return _LEAD_MAP.get(symbol, symbol)


class AlphaSwarmComputeAgent(BaseGroupService):
    """Single service dispatching all alpha agents.

    Per D-32: extends BaseGroupService, one bar consumer, one signal consumer,
    one DB pool (from super()), one LineageRecorder, one LLMProviderChain, one AIContextCache.
    Agents are pure compute, iterated per signal via asyncio.gather().

    Plan 78-01: Write path is LineageRecorder -> topic_signal_lineage() -> LineageWriterAgent -> signal_lineage.
    """

    group_id = "alpha"
    has_graduation = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self.settings = settings
        self._lineage: LineageRecorder | None = None
        self._demotion_streak: int = 0  # consecutive negative-rho cycles (D-25)

        # Agent registry -- pure compute, no infrastructure
        self._agents = [
            SkepticAgentComputeAgent(llm_chain=self._llm_chain),
            CorrelationAgentComputeAgent(llm_chain=self._llm_chain),
            VolumeAgentComputeAgent(llm_chain=self._llm_chain),
        ]

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
        """Topics for bar data that update AIContextCache."""
        return [
            topic_market_bars(self.settings.env_name),
            topic_market_bars_htf(self.settings.env_name),
        ]

    async def _setup(self) -> None:
        """Wire infrastructure beyond BaseGroupService defaults.

        POOL-FIX: pool is created once by super()._setup() in BaseGroupService.
        LineageRecorder gets the Kafka producer from self._producer (set by super).

        Plan 78-03: also enrolls skeptic_v1 in shadow_registry (idempotent).
        """
        await super()._setup()

        # Single LineageRecorder for all swarm prediction events
        # self._producer and self.env_name are set by BaseGroupService._setup()
        self._lineage = LineageRecorder(
            producer=self._producer,
            env_name=self.env_name,
        )

        # D-23: idempotent enrollment — guarantees row exists even if migration missed
        if self._pool is not None:
            await self._shadow_registry_ensure_swarm()

        agent_ids = [a.agent_id for a in self._agents]
        self.logger.info("alpha_swarm.started", agents=agent_ids)

    async def _shadow_registry_ensure_swarm(self) -> None:
        """Idempotent enrollment of skeptic_v1 in shadow_registry as component_type='swarm_agent'.

        Mirrors shadow_registry_ensure() from register_plugins.py.
        ON CONFLICT DO NOTHING preserves any manually-tuned gate params.
        D-23, D-26.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO shadow_registry (component_name, component_type, is_shadow)
                VALUES ('skeptic_v1', 'swarm_agent', TRUE)
                ON CONFLICT (component_name) DO NOTHING
                """,
            )
        self.logger.info("alpha_swarm.shadow_enrolled", component_name="skeptic_v1")

    async def _graduation_loop(self) -> None:
        """Override BaseGroupService stub: evaluate skeptic_v1 every 15 min.

        Runs Spearman ρ on (multiplier vs pnl_r) from signal_lineage JOIN signal_ledger.
        Promotion: n >= 100 AND rho > 0 AND p < 0.05 → is_shadow=FALSE.
        Demotion: 3 consecutive rho < 0 cycles from live state → is_shadow=TRUE.
        D-05, D-06, D-07.
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
        """Single evaluation cycle: query lineage, compute Spearman, apply gates.

        Extracted as a public-ish method for unit-testing without the sleep loop.
        T-78-08: malformed prediction dicts are filtered; non-numeric rows dropped.
        T-78-09: hard N gate before Spearman.
        T-78-10: WHERE clause scoped to component_type='swarm_agent'.
        T-78-11: LIMIT 5000 prevents unbounded scan.
        """
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT l.prediction, s.pnl_r
                FROM signal_lineage l
                JOIN signal_ledger s ON l.signal_id = s.signal_id
                WHERE l.event_type = 'agent_prediction'
                  AND l.source = 'skeptic_v1'
                  AND s.outcome IS NOT NULL
                ORDER BY l.ts DESC
                LIMIT 5000
                """,
            )

        # Extract (prediction_score, pnl_r) pairs, filtering malformed rows (T-78-08)
        predictions: list[float] = []
        pnl_rs: list[float] = []
        dropped = 0
        for row in rows:
            pred_raw = row["prediction"]
            pnl_r_raw = row["pnl_r"]

            # prediction is JSONB dict from asyncpg — extract the scalar score value
            if isinstance(pred_raw, dict):
                score_raw = pred_raw.get("score") or pred_raw.get("multiplier")
            else:
                score_raw = pred_raw

            # Filter non-numeric or missing values
            try:
                score = float(score_raw)
                pnl_r = float(pnl_r_raw)
            except (TypeError, ValueError):
                dropped += 1
                continue

            if not (math.isfinite(score) and math.isfinite(pnl_r)):
                dropped += 1
                continue

            predictions.append(score)
            pnl_rs.append(pnl_r)

        n_resolved = len(predictions)
        if dropped > 0:
            self.logger.warning("graduation_cycle.dropped_rows", dropped=dropped, n=n_resolved)

        # T-78-09: hard N gate — no Spearman below threshold; write progress counter
        if n_resolved < _GRAD_MIN_N:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE shadow_registry
                    SET last_eval_n = $1,
                        last_eval_at = NOW()
                    WHERE component_type = 'swarm_agent'
                      AND component_name = 'skeptic_v1'
                    """,
                    n_resolved,
                )
            self.logger.info(
                "graduation_cycle",
                n=n_resolved,
                rho=None,
                p=None,
                state="shadow",
                streak=self._demotion_streak,
            )
            return

        # Compute Spearman correlation (nan from constant arrays → rho=0, p=1)
        rho_raw, p_raw = spearmanr(predictions, pnl_rs)
        rho: float = 0.0 if math.isnan(float(rho_raw)) else float(rho_raw)
        p: float = 1.0 if math.isnan(float(p_raw)) else float(p_raw)

        # Read current state (T-78-10: scoped to component_type='swarm_agent')
        async with self._pool.acquire() as conn:
            state_row = await conn.fetchrow(
                """
                SELECT is_shadow
                FROM shadow_registry
                WHERE component_type = 'swarm_agent'
                  AND component_name = 'skeptic_v1'
                """,
            )

        is_shadow: bool = True  # default: treat as shadow if row missing
        if state_row is not None:
            is_shadow = bool(state_row["is_shadow"])

        new_is_shadow = is_shadow
        new_state_label = "shadow" if is_shadow else "live"

        # Promotion gate (D-24): shadow + rho > 0 + p < 0.05 → promote to live
        if is_shadow and rho > 0 and p < 0.05:
            new_is_shadow = False
            new_state_label = "live"
            self._demotion_streak = 0

        # Demotion gate (D-25): live + rho < 0 for _GRAD_DEMOTION_STREAK cycles → demote
        elif not is_shadow:
            if rho < 0:
                self._demotion_streak += 1
            else:
                self._demotion_streak = 0

            if self._demotion_streak >= _GRAD_DEMOTION_STREAK:
                new_is_shadow = True
                new_state_label = "shadow"
                self._demotion_streak = 0

        # Persist updated state (T-78-10: WHERE scoped to swarm_agent)
        # Use actual 077 schema columns: last_eval_n, last_eval_ev_r (rho stored here)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE shadow_registry
                SET is_shadow = $1,
                    last_eval_n = $2,
                    last_eval_ev_r = $3,
                    last_eval_at = NOW()
                WHERE component_type = 'swarm_agent'
                  AND component_name = 'skeptic_v1'
                """,
                new_is_shadow,
                n_resolved,
                rho,
            )

        self.logger.info(
            "graduation_cycle",
            n=n_resolved,
            rho=round(rho, 4),
            p=round(p, 4),
            state=new_state_label,
            streak=self._demotion_streak,
        )

    async def _teardown(self) -> None:
        """Flush lineage recorder before base teardown."""
        if self._lineage is not None:
            await self._lineage.flush()
        await super()._teardown()

    async def _handle_trigger(self, event: dict) -> None:
        """Unpack i7.signals envelope and dispatch each signal."""
        for raw_signal in event.get("signals", []):
            await self._process_one_signal(raw_signal)

    async def _process_one_signal(self, raw_signal: dict) -> None:
        """Process a single I7 ranked signal through all swarm agents.

        - TF gate (5m+ only)
        - Lead context enrichment via _LEAD_MAP (_resolve_lead)
        - SwarmAgent calls
        - LineageRecorder write (single path, no Shadow/Transform)
        """
        try:
            signal = signal_dict_to_ranked(raw_signal)
        except Exception as e:
            self.logger.warning("alpha_swarm.invalid_trigger", signal=raw_signal, exc_info=e)
            return

        symbol = signal.symbol
        tf = signal.tf

        # Per D-09: filter to 5m+ TF only
        if tf not in _ELIGIBLE_TFS:
            return

        signal_id = signal.signal_id or uuid4()
        signal_dict = signal.model_dump()

        context = self._context_cache.build(
            symbol=symbol,
            tf=tf,
            tiers_needed=frozenset(),
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

        enriched = self._enrich_context(context)

        # D-18: BaseAIAgent.compute() already provides asyncio.wait_for + neutral
        # fallback — SafeAgentWrapper deleted in Phase 78.
        tasks = []
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

            tasks.append(agent.compute(self._enrich_context(agent_context)))

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.error(
                    "alpha_swarm.agent_exception",
                    error=str(result),
                )
                continue
            if isinstance(result, AgentOutput):
                await self._record_swarm_result(signal_id, enriched, result)
                await self._publish_result(result)

                if result.error:
                    self.logger.info(
                        "alpha_swarm.neutral_result",
                        agent_id=result.agent_id,
                        signal_id=str(signal_id),
                        error=result.error,
                    )
                else:
                    self.logger.info(
                        "alpha_swarm.prediction",
                        agent_id=result.agent_id,
                        signal_id=str(signal_id),
                        symbol=symbol,
                        tf=tf,
                    )

    async def _record_swarm_result(
        self,
        signal_id: Any,
        enriched: AIContext,
        result: AgentOutput,
    ) -> None:
        """Record swarm agent prediction via LineageRecorder -> topic_signal_lineage().

        Single write path to signal_lineage (D-01, D-04, D-08):
        - segment_key = f"{hmm_regime}.{timeframe}" (numeric prefix, D-35)
        - Logs warning + skips if hmm_regime is None (T-78-02 mitigation)
        - signal_id converted to str() per CLAUDE.md UUID rule
        """
        if self._lineage is None:
            return

        # Build segment_key from I4 hmm_regime (numeric) + timeframe
        hmm_regime = enriched.i4.hmm_regime if enriched.i4 is not None else None
        if hmm_regime is None:
            self.logger.warning(
                "alpha_swarm.missing_hmm_regime",
                kind="missing_hmm_regime",
                signal_id=str(signal_id),
                agent_id=result.agent_id,
                symbol=enriched.symbol,
                tf=enriched.timeframe,
            )
            return

        segment_key = f"{hmm_regime}.{enriched.timeframe}"
        multiplier = result.payload.get("multiplier", 1.0)

        self._lineage.record(
            signal_id=signal_id,
            event_type="agent_prediction",
            source=result.agent_id,
            multiplier=multiplier,
            metadata={
                "segment_key": segment_key,
                "confidence": result.payload.get("confidence", 0.0),
                "group": result.group,
                "payload": result.payload,
            },
            symbol=enriched.symbol,
            tf=enriched.timeframe,
        )

    def _enrich_context(self, ctx: AIContext) -> AIContext:
        """Enrich AIContext with agent-specific data.

        Per D-16: uses model_copy(update={...}) to create enriched copy.
        No object.__setattr__ hacks -- proper Pydantic fields.

        D-10 fix: uses AIContextCache.get_lead() instead of private _cache access.
        D-38: volume_profile field removed; VolumeZscorePlugin (Plan 06) provides volume data.
        """
        # Lead index context for CorrelationAgent
        lead_context = self._find_lead_context(
            ctx.symbol,
            ctx.timeframe,
            ctx,
        )

        return ctx.model_copy(
            update={
                "lead_context": lead_context,
            }
        )

    def _find_lead_context(
        self,
        symbol: str,
        tf: str,
        ctx: AIContext,
    ) -> AIContext | None:
        """Look up lead index AIContext from cache using _LEAD_MAP.

        Per D-10 fix: uses AIContextCache.get_lead() public method.
        Per D-36/D-37: uses _LEAD_MAP via _resolve_lead() — no inline conditionals.

        Returns None if no lead mapping, self-lead, or cache miss.
        """
        # Extract base from contract symbol (e.g. "ESM6" -> "ES")
        import re

        base_match = re.match(r"^([A-Z]+?)[A-Z]\d+$", symbol)
        if not base_match:
            return None
        base = base_match.group(1)

        lead_base = _resolve_lead(base)
        if lead_base == base:
            return None  # self-lead — no enrichment needed

        # D-10: Use public get_lead() method instead of private _cache access
        return self._context_cache.get_lead(symbol, tf, _LEAD_MAP)


def main() -> None:
    settings = Settings()
    service = AlphaSwarmComputeAgent(settings)
    import asyncio

    asyncio.run(service.start())


if __name__ == "__main__":
    main()
