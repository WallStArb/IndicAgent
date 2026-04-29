"""alpha_swarm_agent.py -- AlphaSwarmComputeAgent extending BaseGroupService.

Per B+ architecture: one service, all alpha agents, extends BaseGroupService.
group_id="alpha", has_graduation=True
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import uuid4

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog

from src.config.settings import Settings
from src.core.ai.base_group_service import BaseGroupService
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput
from src.core.ml.shadow import ShadowRecorder
from src.core.ml.transform_recorder import TransformRecorder
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_swarm_alpha,
)
from src.intelligence.ai.alpha.correlation_agent import CorrelationAgentComputeAgent
from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent
from src.intelligence.ai.alpha.volume_agent import VolumeAgentComputeAgent

logger = structlog.get_logger(__name__)

_ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

# Locked mapping: swarm agent_id → (transform_id, dag_order) for signal_transform_log
_SWARM_AGENT_TO_TRANSFORM: dict[str, tuple[str, int]] = {
    "skeptic_v1": ("swarm_skeptic", 6),
    "correlation_v1": ("swarm_correlation", 7),
    "volume_v1": ("swarm_volume", 8),
}

# Lead index mapping: symbol base -> lead index base
_LEAD_INDEX_MAP: dict[str, str] = {
    "ES": "ES",
    "NQ": "ES",
    "RTY": "ES",
    "YM": "ES",
    "CL": "CL",
    "HO": "CL",
    "RB": "CL",
    "GC": "GC",
    "SI": "GC",
    "HG": "GC",
    "ZN": "ZN",
    "ZB": "ZN",
    "ZF": "ZN",
    "ZT": "ZN",
    "VX": "VX",
}

_SYMBOL_BASE_RE = re.compile(r"^([A-Z]+?)[A-Z]\d+$")


class AlphaSwarmComputeAgent(BaseGroupService):
    """Single service dispatching all alpha agents.

    Per D-32: extends BaseGroupService, one bar consumer, one signal consumer,
    one DB pool, one ShadowRecorder, one LLMProviderChain, one AIContextCache.
    Agents are pure compute, iterated per signal via asyncio.gather().
    """

    group_id = "alpha"
    has_graduation = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings)
        self.settings = settings
        self._recorder: ShadowRecorder | None = None
        self._transform_recorder: TransformRecorder | None = None

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

    def _bar_topic(self) -> str:
        """Topic for bar data that updates AIContextCache."""
        # Subscribe to both 1m and HTF bars
        return ",".join(
            [
                topic_market_bars(self.settings.env_name),
                topic_market_bars_htf(self.settings.env_name),
            ]
        )

    async def _setup(self) -> None:
        """Wire infrastructure beyond BaseGroupService defaults."""
        await super()._setup()

        # DB pool + ShadowRecorder
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self.settings.database_url,
            min_size=2,
            max_size=5,
        )
        self._recorder = ShadowRecorder(
            self._pool,
            batch_size=50,
            flush_interval_s=2.0,
        )
        self._transform_recorder = TransformRecorder(
            self._pool,
            batch_size=50,
            flush_interval_s=2.0,
        )

        agent_ids = [a.agent_id for a in self._agents]
        self.logger.info("alpha_swarm.started", agents=agent_ids)

    async def _teardown(self) -> None:
        """Flush recorder before base teardown."""
        if self._recorder:
            await self._recorder.flush()
        if self._transform_recorder:
            await self._transform_recorder.flush()
        await super()._teardown()

    async def _handle_trigger(self, event: dict) -> None:
        """Process a single I7 winner signal through all agents.

        Overrides BaseGroupService._handle_trigger to add:
        - TF gate (5m+ only)
        - Volume profile enrichment
        - Lead context enrichment (D-10 fix: uses get_lead())
        - SwarmAggregator calls
        - ShadowRecorder + TransformRecorder writes
        """
        from src.intelligence.schemas import RankedSignal

        try:
            signal = RankedSignal(**event)
        except Exception:
            self.logger.warning("alpha_swarm.invalid_trigger", event=event)
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

        from src.core.ai.safe_wrapper import SafeAgentWrapper

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

            wrapper = SafeAgentWrapper(agent)
            tasks.append(wrapper.compute(self._enrich_context(agent_context)))

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
        """Dual-write: ShadowRecorder (alpha_multiplier_shadow) + TransformRecorder."""
        # 1. ShadowRecorder write (existing alpha_multiplier_shadow path — unchanged)
        if self._recorder:
            multiplier = result.payload.get("multiplier", 1.0)
            confidence = result.payload.get("confidence", 0.0)
            await self._recorder.record(
                signal_id=signal_id,
                agent_id=result.agent_id,
                multiplier=multiplier,
                confidence=confidence,
                symbol=enriched.symbol,
                tf=enriched.timeframe,
                regime=enriched.i4.hmm_regime if enriched.i4 else None,
                group=result.group,
                features=result.payload,
            )

        # 2. TransformRecorder dual-write (Phase 1 bridge — swarm half of registry)
        mapping = _SWARM_AGENT_TO_TRANSFORM.get(result.agent_id)
        if mapping is not None and self._transform_recorder is not None:
            transform_id, dag_order = mapping
            seg = (
                f"{enriched.i4.hmm_regime}.{enriched.timeframe}"
                if enriched.i4
                else f"unknown.{enriched.timeframe}"
            )
            multiplier = result.payload.get("multiplier", 1.0)
            await self._transform_recorder.record(
                signal_id=signal_id,
                transform_id=transform_id,
                dag_order=dag_order,
                multiplier=multiplier,
                segment_key=seg,
                metadata=result.payload,
            )
        elif mapping is None:
            self.logger.warning(
                "alpha_swarm.unmapped_agent_for_transform_log",
                agent_id=result.agent_id,
            )

    def _enrich_context(self, ctx: AIContext) -> AIContext:
        """Enrich AIContext with agent-specific data.

        Per D-16: uses model_copy(update={...}) to create enriched copy.
        No object.__setattr__ hacks -- proper Pydantic fields.

        D-10 fix: uses AIContextCache.get_lead() instead of private _cache access.
        """
        # Lead index context for CorrelationAgent
        lead_context = self._find_lead_context(
            ctx.symbol,
            ctx.timeframe,
            ctx,
        )

        # Volume profile data for VolumeAgent
        volume_profile = self._extract_volume_profile(
            ctx.symbol,
            ctx.timeframe,
        )

        return ctx.model_copy(
            update={
                "lead_context": lead_context,
                "volume_profile": volume_profile,
            }
        )

    def _find_lead_context(
        self,
        symbol: str,
        tf: str,
        ctx: AIContext,
    ) -> AIContext | None:
        """Look up lead index AIContext from cache.

        Per D-10 fix: uses AIContextCache.get_lead() public method instead of
        accessing private self._context_cache._cache.

        Returns None if no lead mapping, self-lead, or cache miss.
        """
        base_match = _SYMBOL_BASE_RE.match(symbol)
        if not base_match:
            return None
        base = base_match.group(1)
        lead_base = _LEAD_INDEX_MAP.get(base)
        if lead_base is None or lead_base == base:
            return None  # self-lead or no mapping

        # D-10: Use public get_lead() method instead of private _cache access
        return self._context_cache.get_lead(symbol, tf, _LEAD_INDEX_MAP)

    def _extract_volume_profile(
        self,
        symbol: str,
        tf: str,
    ) -> dict[str, Any] | None:
        """Extract I4 volume profile fields from cache internal data.

        Reads raw i4 JSONB fields that are NOT in AIContext but exist
        in intelligence_features. Uses private _cache access here because
        AIContextCache doesn't expose volume profile data (not all agents need it).

        TODO: Add AIContextCache.get_volume_profile() in future plan to eliminate
        this private access (currently out of scope for this plan).
        """
        # VolumeAgent uses I4 context directly
        return None


def main() -> None:
    settings = Settings()
    service = AlphaSwarmComputeAgent(settings)
    import asyncio

    asyncio.run(service.start())


if __name__ == "__main__":
    main()
