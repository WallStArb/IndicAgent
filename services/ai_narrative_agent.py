"""AINarrativeComputeAgent — thin Kafka wrapper around NarrativeOrchestrator.

Subscribes to intelligence journal topic, generates LLM narrative per signal,
publishes to narratives topic. All narrative logic is in src/intelligence/narrative/.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.llm.chain import LLMProviderChain
from src.core.stream_keys import topic_intelligence_journal, topic_narratives
from src.intelligence.narrative.orchestrator import NarrativeOrchestrator
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG

logger = structlog.get_logger(__name__)


class AINarrativeComputeAgent(BaseAgent):
    """Thin agent: consume BarIntelligenceRecord → generate narrative → publish."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("AINarrativeComputeAgent")
        self.settings = settings
        chain = LLMProviderChain(call_type="narrative", settings=settings)
        self._orchestrator = NarrativeOrchestrator(chain=chain, max_tokens=200, timeout=30.0)
        # Kafka clients created in _setup() — AIOKafkaConsumer requires a running event loop.
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

    async def _setup(self) -> None:
        self._consumer = KafkaConsumerClient(
            topic_intelligence_journal(self.settings.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="ai_narrative_consumer",
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._consumer.start()
        await self._consumer.skip_lag_if_needed(max_lag=100)
        await self._producer.start()

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event. Stream processor — no buffer accumulation."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(0)
            await asyncio.sleep(15)

    async def _teardown(self) -> None:
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def _run(self) -> None:
        """Main loop: consume records, generate narratives, publish."""
        self.logger.info("ai_narrative_agent.starting")
        assert self._consumer is not None, "_run called before _setup"
        lag_task = asyncio.create_task(self._report_consumer_lag())
        try:
            async for _topic, _key, payload in self._consumer.messages():
                if self._stop_event.is_set():
                    break
                try:
                    await self._process_bar(payload)
                except Exception as exc:
                    self.logger.exception("ai_narrative_agent.consume_error", error=str(exc))
        finally:
            lag_task.cancel()
            try:
                await lag_task
            except asyncio.CancelledError:
                pass

    # Drop bars older than this — prevents wasting LLM tokens on replay/stale data.
    _STALENESS_LIMIT = timedelta(minutes=10)

    async def _process_bar(self, record: Any) -> None:
        """Generate and publish a narrative for one BarIntelligenceRecord payload.

        `record` may be a dict (raw Kafka payload) or a BarIntelligenceRecord object.
        Wraps the payload in a lightweight adapter so NarrativeOrchestrator can
        access .intelligence.symbol / .tf / .ts and .winner_direction.
        """
        try:
            # Adapt dict payload to object with attribute access
            adapted = _RecordAdapter(record) if isinstance(record, dict) else record

            # Freshness gate — skip stale bars (replay, backfill, lag) to avoid
            # wasting LLM tokens on data that is no longer actionable.
            bar_ts_raw = adapted.intelligence.ts
            if bar_ts_raw:
                try:
                    bar_ts = (
                        bar_ts_raw
                        if isinstance(bar_ts_raw, datetime)
                        else datetime.fromisoformat(str(bar_ts_raw))
                    )
                    if bar_ts.tzinfo is None:
                        bar_ts = bar_ts.replace(tzinfo=UTC)
                    age = datetime.now(UTC) - bar_ts
                    if age > self._STALENESS_LIMIT:
                        self.logger.info(
                            "ai_narrative_agent.skipped_stale_bar",
                            symbol=adapted.intelligence.symbol,
                            tf=adapted.intelligence.tf,
                            bar_age_s=round(age.total_seconds()),
                        )
                        return
                except (ValueError, TypeError):
                    pass  # Unparseable ts — let it through rather than block

            narrative = await self._orchestrator.generate(adapted)
            if narrative is None:
                return

            intel = adapted.intelligence
            topic = topic_narratives(self.settings.env_name)
            await self._producer.publish(
                topic,
                {
                    "symbol": intel.symbol,
                    "tf": intel.tf,
                    "ts": intel.ts.isoformat() if hasattr(intel.ts, "isoformat") else intel.ts,
                    "narrative": narrative,
                    "record_id": getattr(adapted, "record_id", None),
                },
            )
        except Exception as exc:
            self.logger.exception("ai_narrative_agent.process_error", error=str(exc))


class _IntelAdapter:
    """Lightweight adapter for the intelligence sub-dict."""

    __slots__ = ("symbol", "tf", "ts")

    def __init__(self, d: dict) -> None:
        self.symbol = d.get("symbol", "")
        self.tf = d.get("tf", "")
        self.ts = d.get("ts", "")


class _RecordAdapter:
    """Lightweight adapter for raw dict BarIntelligenceRecord payloads."""

    __slots__ = ("intelligence", "winner_direction", "winner_confidence", "winner_plugin", "record_id")

    def __init__(self, d: dict) -> None:
        intel_raw = d.get("intelligence", {})
        self.intelligence = _IntelAdapter(intel_raw if isinstance(intel_raw, dict) else {})
        self.winner_direction = d.get("winner_direction")
        self.winner_confidence = d.get("winner_confidence")
        self.winner_plugin = d.get("winner_plugin")
        self.record_id = d.get("record_id")


def main() -> None:
    settings = Settings()
    agent = AINarrativeComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
