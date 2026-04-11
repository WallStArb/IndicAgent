"""SwarmOrchestratorComputeAgent — two-phase signal processing for swarm contributors.

Bar loop: subscribe to topic_market_bars + topic_market_bars_htf → update SwarmContextCache.
Signal loop: subscribe to topic_intelligence_i7_signals → build context → run Path A contributors
             (asyncio.gather) → fan-out each AgentResult to topic_swarm_results()
             → assemble AlphaMultiplier → publish to topic_swarm_alpha_path_a().
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import (
    topic_intelligence_i7_signals,
    topic_market_bars,
    topic_market_bars_htf,
    topic_swarm_alpha_path_a,
    topic_swarm_orchestrator_dlq,
    topic_swarm_results,
)
from src.intelligence.swarm.aggregator import SwarmAggregator
from src.intelligence.swarm.context import SwarmContextCache
from src.intelligence.swarm.safety import SafeSwarmWrapper

logger = structlog.get_logger(__name__)


class SwarmOrchestratorComputeAgent(BaseAgent):
    """Orchestrate swarm contributors for each I7 signal."""

    def __init__(self, settings: Settings, contributors: list | None = None) -> None:
        super().__init__(name="SwarmOrchestratorComputeAgent")
        self._settings = settings
        self._context_cache = SwarmContextCache()
        self._contributors = [SafeSwarmWrapper(c) for c in (contributors or [])]
        self._aggregator = SwarmAggregator()
        self._bar_consumer: KafkaConsumerClient | None = None
        self._signal_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

    async def _setup(self) -> None:
        env = self._settings.env_name
        self._bar_consumer = KafkaConsumerClient(
            topic_market_bars(env),
            topic_market_bars_htf(env),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="swarm_orchestrator_bar_consumer",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()

        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(env),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="swarm_orchestrator_signal_consumer",
            auto_offset_reset="latest",
        )
        await self._signal_consumer.start()

        self._producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
        )
        await self._producer.start()
        self.logger.info("swarm_orchestrator.started")

    async def _teardown(self) -> None:
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
            self._record_message_consumed()
            await self._handle_bar(payload)

    async def _signal_loop(self) -> None:
        assert self._signal_consumer is not None
        async for _topic, _key, payload in self._signal_consumer.messages():
            self._record_message_consumed()
            symbol = (
                payload.get("symbol")
                if isinstance(payload, dict)
                else getattr(payload, "symbol", None)
            )
            tf = payload.get("tf") if isinstance(payload, dict) else getattr(payload, "tf", None)
            await self._handle_signal(payload, symbol=symbol, tf=tf)

    async def _handle_bar(self, event: Any) -> None:
        """Update context cache from IntelligenceEvent."""
        try:
            self._context_cache.update(event)
        except Exception as exc:
            self.logger.warning("swarm_orchestrator.bar_cache_error", error=str(exc))

    async def _handle_signal(self, signal: Any, symbol: str | None, tf: str | None) -> None:
        """Run contributors, fan-out results, assemble and publish AlphaMultiplier."""
        assert self._producer is not None
        signal_id = uuid4()
        ctx = self._context_cache.build(
            symbol=symbol or "",
            tf=tf or "",
            signal=signal,
            signal_id=signal_id,
        )
        if ctx is None:
            await self._producer.publish(
                topic_swarm_orchestrator_dlq(self._settings.env_name),
                {"error": "no_context", "symbol": symbol, "tf": tf},
            )
            return

        # Path A: run all deterministic contributors concurrently
        path_a_wrappers = [
            w for w in self._contributors if w.path == "deterministic"
        ]
        path_a_results = list(await asyncio.gather(*[w.run(ctx) for w in path_a_wrappers]))

        # Fan-out each AgentResult to swarm results topic
        env = self._settings.env_name
        for result in path_a_results:
            await self._producer.publish(
                topic_swarm_results(env),
                {
                    "signal_id": str(signal_id),
                    "agent_id": result.agent_id,
                    "symbol": ctx.symbol,
                    "tf": ctx.timeframe,
                    "ts": ctx.ts.isoformat() if hasattr(ctx.ts, "isoformat") else str(ctx.ts),
                    "multiplier": result.multiplier,
                    "confidence": result.confidence,
                    "path": "path_a",
                    "shadow_only": result.shadow_only,
                    "hmm_regime": ctx.hmm_regime,
                    "features": None,  # ShadowRecorder (Plan 56-08) adds features
                    "latency_ms": result.latency_ms,
                },
            )

        # Assemble AlphaMultiplier and publish
        ts = ctx.ts if isinstance(ctx.ts, datetime) else datetime.now(UTC)
        alpha = self._aggregator.aggregate(
            signal_id=signal_id,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            ts=ts,
            path_a_results=path_a_results,
            path_b_results=[],
        )

        await self._producer.publish(
            topic_swarm_alpha_path_a(env),
            {
                "signal_id": str(alpha.signal_id),
                "symbol": alpha.symbol,
                "timeframe": alpha.timeframe,
                "ts": alpha.ts.isoformat(),
                "path_a_multiplier": alpha.path_a_multiplier,
                "final_alpha_multiplier": alpha.final_alpha_multiplier,
                "production_multiplier": alpha.production_multiplier,
                "shadow_only": alpha.shadow_only,
                "contributor_count": len(path_a_results),
            },
        )


def main() -> None:
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent(settings, contributors=[])
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
