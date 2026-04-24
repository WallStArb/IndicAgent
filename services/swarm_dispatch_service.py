"""swarm_dispatch_service.py -- single service dispatching all swarm agents.

Per D-15: ONE SwarmDispatchService owns all infrastructure.
Agents are pure compute classes registered in self._agents.
Per D-09: Filters to 5m+ TF only.
Per D-08: SwarmContext seeded from DB on startup.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.llm.chain import LLMProviderChain
from src.core.ml.shadow import ShadowRecorder
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_swarm_results,
)
from src.intelligence.swarm.agents.skeptic_agent import SkepticAgentComputeAgent
from src.intelligence.swarm.context import SwarmContext, SwarmContextCache

logger = structlog.get_logger(__name__)

_ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

# Lead index mapping: symbol base -> lead index base
_LEAD_INDEX_MAP: dict[str, str] = {
    "ES": "ES", "NQ": "ES", "RTY": "ES", "YM": "ES",
    "CL": "CL", "HO": "CL", "RB": "CL",
    "GC": "GC", "SI": "GC", "HG": "GC",
    "ZN": "ZN", "ZB": "ZN", "ZF": "ZN", "ZT": "ZN",
    "VX": "VX",
}

# I4 volume profile fields to extract for VolumeAgent
_VOLUME_PROFILE_FIELDS = (
    "vah", "val", "vah_rolling", "val_rolling",
    "price_in_value_area", "distance_to_vah_atr", "distance_to_val_atr",
)


def _safe(obj: Any, attr: str) -> Any:
    """Null-safe getattr -- mirrors SwarmContextCache.build() helper."""
    return getattr(obj, attr, None)


class SwarmDispatchService(BaseAgent):
    """Single service dispatching all swarm agents.

    Per D-15: one bar consumer, one signal consumer, one DB pool,
    one ShadowRecorder, one LLMProviderChain, one SwarmContextCache.
    Agents are pure compute, iterated per signal via asyncio.gather().
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(name="SwarmDispatchService", max_idle_seconds=300)
        self.settings = settings

        # Shared infrastructure
        self._llm_chain = LLMProviderChain(
            call_type="swarm", settings=settings, cache_ttl=300.0,
        )
        self._context_cache = SwarmContextCache()
        self._recorder: ShadowRecorder | None = None

        # Agent registry -- pure compute, no infrastructure
        self._agents = [
            SkepticAgentComputeAgent(llm_chain=self._llm_chain),
            # CorrelationAgent and VolumeAgent added in Plan 02
        ]

        # Kafka (initialized in _setup)
        self._bar_consumer: KafkaConsumerClient | None = None
        self._signal_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

    async def _setup(self) -> None:
        env = self.settings.env_name

        # Bar consumer for context cache warmth
        self._bar_consumer = KafkaConsumerClient(
            topic_market_bars(env),
            topic_market_bars_htf(env),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="swarm_dispatch_bar_consumer",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()

        # Signal consumer
        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(env),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="swarm_dispatch_signal_consumer",
            auto_offset_reset="latest",
        )
        await self._signal_consumer.start()

        # Producer for swarm results
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        # DB pool + ShadowRecorder
        pool = await asyncpg.create_pool(
            self.settings.database_url, min_size=2, max_size=5,
        )
        self._recorder = ShadowRecorder(
            pool, batch_size=50, flush_interval_s=2.0,
        )

        # Per D-08: seed context cache from DB
        await self._seed_context_cache(pool)

        agent_ids = [a.agent_id for a in self._agents]
        self.logger.info("swarm_dispatch.started", agents=agent_ids)

    async def _teardown(self) -> None:
        if self._recorder:
            await self._recorder.flush()
        if self._bar_consumer:
            await self._bar_consumer.stop()
        if self._signal_consumer:
            await self._signal_consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def _run(self) -> None:
        bar_task = asyncio.create_task(self._bar_loop())
        signal_task = asyncio.create_task(self._signal_loop())
        try:
            await asyncio.gather(bar_task, signal_task)
        except Exception:
            bar_task.cancel()
            signal_task.cancel()
            raise

    async def _bar_loop(self) -> None:
        assert self._bar_consumer is not None
        async for _topic, _key, payload in self._bar_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                self._context_cache.update(payload)
            except Exception as exc:
                self.logger.warning(
                    "swarm_dispatch.bar_cache_error", error=str(exc),
                )

    async def _signal_loop(self) -> None:
        assert self._signal_consumer is not None
        async for _topic, _key, payload in self._signal_consumer.messages():
            if not self.running:
                break
            self._record_message_consumed()
            try:
                await self._handle_signal(payload)
            except Exception as exc:
                self.logger.exception(
                    "swarm_dispatch.signal_error", error=str(exc),
                )

    async def _handle_signal(self, signal: Any) -> None:
        """Process a single I7 winner signal through all agents."""
        symbol = (
            signal.get("symbol") if isinstance(signal, dict)
            else getattr(signal, "symbol", None)
        )
        tf = (
            signal.get("tf") if isinstance(signal, dict)
            else getattr(signal, "tf", None)
        )

        # Per D-09: filter to 5m+ TF only
        if tf not in _ELIGIBLE_TFS:
            return

        signal_id = uuid4()
        ctx = self._context_cache.build(
            symbol=symbol or "", tf=tf or "",
            signal=signal, signal_id=signal_id,
        )
        if ctx is None:
            self.logger.warning(
                "swarm_dispatch.no_context", symbol=symbol, tf=tf,
            )
            return

        # Per D-16: enrich context with lead index + volume profile
        enriched = self._enrich_context(ctx)

        # Run ALL agents concurrently per D-15
        results = await asyncio.gather(
            *[agent.compute(enriched) for agent in self._agents]
        )

        # Record each result via shared ShadowRecorder
        for result in results:
            if self._recorder:
                await self._recorder.record(
                    signal_id=signal_id,
                    agent_id=result.agent_id,
                    multiplier=result.multiplier,
                    confidence=result.confidence,
                    symbol=enriched.symbol,
                    tf=enriched.timeframe,
                    regime=enriched.hmm_regime,
                    path=result.path,
                    features=result.metadata,
                )

            # Publish to swarm results topic
            assert self._producer is not None
            await self._producer.publish(
                topic_swarm_results(self.settings.env_name),
                {
                    "signal_id": str(signal_id),
                    "agent_id": result.agent_id,
                    "symbol": enriched.symbol,
                    "tf": enriched.timeframe,
                    "multiplier": result.multiplier,
                    "confidence": result.confidence,
                    "path": result.path,
                    "shadow_only": result.shadow_only,
                    "hmm_regime": enriched.hmm_regime,
                    "features": result.metadata,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                },
            )

            if result.error:
                self.logger.info(
                    "swarm_dispatch.neutral_result",
                    agent_id=result.agent_id,
                    signal_id=str(signal_id),
                    error=result.error,
                )
            else:
                self.logger.info(
                    "swarm_dispatch.prediction",
                    agent_id=result.agent_id,
                    signal_id=str(signal_id),
                    symbol=symbol,
                    tf=tf,
                    multiplier=result.multiplier,
                )

    def _enrich_context(self, ctx: SwarmContext) -> SwarmContext:
        """Enrich SwarmContext with agent-specific data.

        Per D-16: uses model_copy(update={...}) to create enriched copy.
        No object.__setattr__ hacks -- proper Pydantic fields.
        """
        # Lead index context for CorrelationAgent
        lead_context = self._find_lead_context(
            ctx.symbol, ctx.timeframe, ctx,
        )

        # Volume profile data for VolumeAgent
        volume_profile = self._extract_volume_profile(
            ctx.symbol, ctx.timeframe,
        )

        return ctx.model_copy(update={
            "lead_context": lead_context,
            "volume_profile": volume_profile,
        })

    def _find_lead_context(
        self, symbol: str, tf: str, ctx: SwarmContext,
    ) -> SwarmContext | None:
        """Look up lead index SwarmContext from cache.

        Per D-15: context preparation IS the service's job. The agent's
        _compute() just reads context.lead_context -- it doesn't build it.

        Cannot call self._context_cache.build() because that requires a
        RankedSignal which we don't have for the lead index. Instead,
        construct SwarmContext manually from the cache's internal
        SimpleNamespace proxy, using the same field mapping as
        SwarmContextCache.build().

        Returns None if no lead mapping, self-lead, or cache miss.
        """
        base_match = re.match(r"^([A-Z]+?)[A-Z]\d+$", symbol)
        if not base_match:
            return None
        base = base_match.group(1)
        lead_base = _LEAD_INDEX_MAP.get(base)
        if lead_base is None or lead_base == base:
            return None  # self-lead or no mapping

        # Search cache for any symbol matching the lead base prefix
        for (s, _tf), entry in self._context_cache._cache.items():
            if s.startswith(lead_base) and _tf == tf:
                event_proxy, _cached_at = entry
                # Build SwarmContext using same field mapping as build()
                return SwarmContext(
                    signal_id=ctx.signal_id,
                    symbol=s,
                    timeframe=tf,
                    ts=_safe(event_proxy, "ts"),
                    atr=_safe(_safe(event_proxy, "i1"), "atr_14"),
                    adx=_safe(_safe(event_proxy, "i1"), "adx"),
                    rsi=_safe(_safe(event_proxy, "i1"), "rsi_14"),
                    hmm_regime=_safe(
                        _safe(event_proxy, "i4"), "hmm_regime",
                    ),
                    trend_regime=_safe(
                        _safe(event_proxy, "i4"), "trend_regime",
                    ),
                    vol_regime=_safe(
                        _safe(event_proxy, "i4"), "vol_regime",
                    ),
                    vol_percentile=_safe(
                        _safe(event_proxy, "i4"), "vol_percentile",
                    ),
                    garch_vol_ratio=_safe(
                        _safe(event_proxy, "i4"), "garch_vol_ratio",
                    ),
                    garch_vol_regime=_safe(
                        _safe(event_proxy, "i4"), "garch_vol_regime",
                    ),
                    kalman_trend=_safe(
                        _safe(event_proxy, "i4"), "kalman_trend",
                    ),
                    kalman_slope=_safe(
                        _safe(event_proxy, "i4"), "kalman_slope",
                    ),
                    vwap=_safe(_safe(event_proxy, "i4"), "vwap"),
                    poc_price=_safe(
                        _safe(event_proxy, "i4"), "poc_price",
                    ),
                    poc_price_rolling=_safe(
                        _safe(event_proxy, "i4"), "poc_price_rolling",
                    ),
                    ctf_score=_safe(
                        _safe(event_proxy, "i6"), "ctf_score",
                    ),
                    ctf_trend_alignment=_safe(
                        _safe(event_proxy, "i6"), "ctf_trend_alignment",
                    ),
                    ctf_structure_alignment=_safe(
                        _safe(event_proxy, "i6"), "ctf_structure_alignment",
                    ),
                    ctf_regime_agreement=_safe(
                        _safe(event_proxy, "i6"), "ctf_regime_agreement",
                    ),
                    ctf_timeframes_aligned=_safe(
                        _safe(event_proxy, "i6"), "ctf_timeframes_aligned",
                    ),
                    ctf_fvg_alignment=_safe(
                        _safe(event_proxy, "i6"), "ctf_fvg_alignment",
                    ),
                    ctf_ob_alignment=_safe(
                        _safe(event_proxy, "i6"), "ctf_ob_alignment",
                    ),
                    winner_plugin=None,
                    winner_direction=None,
                    winner_confidence=None,
                    price=_safe(_safe(event_proxy, "bar"), "close"),
                    volume=_safe(_safe(event_proxy, "bar"), "volume"),
                )
        return None

    def _extract_volume_profile(
        self, symbol: str, tf: str,
    ) -> dict[str, Any] | None:
        """Extract I4 volume profile fields from cache internal data.

        Reads raw i4 JSONB fields that are NOT in SwarmContext but exist
        in intelligence_features. The cache stores the raw event proxy
        which has i4 attribute with all VolumeProfile fields.
        """
        key = (symbol, tf)
        entry = self._context_cache._cache.get(key)
        if entry is None:
            return None

        event_proxy, _ = entry
        i4 = getattr(event_proxy, "i4", None)
        if i4 is None:
            return None

        vp = {}
        for field in _VOLUME_PROFILE_FIELDS:
            val = getattr(i4, field, None)
            if isinstance(val, (int, float)):
                vp[field] = val
        return vp if vp else None

    async def _seed_context_cache(self, pool: asyncpg.Pool) -> None:
        """Per D-08: seed SwarmContextCache from intelligence_features."""
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (symbol, tf)
                        symbol, tf, ts, bar, i1, i4, i6
                    FROM intelligence_features
                    WHERE ts > NOW() - INTERVAL '7 days'
                      AND i1 IS NOT NULL
                      AND i4 IS NOT NULL
                    ORDER BY symbol, tf, ts DESC
                """)
            loaded = 0
            for row in rows:
                self._context_cache.seed_from_db_row(dict(row))
                loaded += 1
            self.logger.info(
                "swarm_dispatch.cache_seeded", rows=loaded,
            )
        except Exception as exc:
            self.logger.warning(
                "swarm_dispatch.cache_seed_failed", error=str(exc),
            )


def main() -> None:
    settings = Settings()
    service = SwarmDispatchService(settings)
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
