#!/usr/bin/env python3
"""ProviderMergerAgent — canonical gateway from raw provider topics to market.bars.

Subscribes to all configured `market.bars.raw.<provider>` topics.
Routes bars from the authoritative provider to `market.bars`.
Non-authoritative bars are tracked (secondary state) but not forwarded.
Auto-failover when the primary has been silent >= provider_silence_bars_threshold
bar intervals. Recovery event published when primary resumes.
ProviderQualityEvent published to `market.data.quality` on every routed bar,
failover, and recovery.

DB-ignorant ProviderAgent — no database access.
Metrics port: :9130

Golden Signals (D-16):
- Traffic: merger_bars_routed_total, merger_bars_dropped_total
- Latency: merger_bar_latency_seconds
- Errors: (exception counter via structlog)
- Saturation: failover state (merger_failovers_total)

Version: 1.0.0
Last Updated: 2026-03-28
Status: Phase 54 Plan 04
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage
from src.core.schemas.provider_quality import ProviderQualityEvent
from src.core.service_utils import TF_SECONDS
from src.core.stream_keys import (
    message_key,
    topic_market_bars,
    topic_market_bars_raw,
    topic_market_data_quality,
)
from src.observability.metrics import (
    MERGER_BAR_LATENCY_SECONDS,
    MERGER_BARS_DROPPED_TOTAL,
    MERGER_BARS_ROUTED_TOTAL,
    MERGER_FAILOVERS_TOTAL,
)


class ProviderMergerAgent(BaseAgent):
    """Canonical gateway agent that routes raw provider bars to market.bars.

    Single source of truth for the market.bars topic — all 8 downstream
    consumers are untouched by provider topology changes.

    Auto-failover: when primary has been silent >= threshold * bar_interval
    seconds AND secondary has recent data, _promoted[symbol] is set to secondary.

    Recovery: when primary resumes on a promoted symbol, _promoted is cleared
    and a recovery quality event is published.
    """

    def __init__(self) -> None:
        super().__init__(name="provider_merger_agent", metrics_port=9130)
        self._provider_raw_topics: list[str] = self.settings.provider_raw_topics
        if not self._provider_raw_topics:
            raise ValueError("provider_raw_topics must be non-empty")
        self._provider_routing_config: dict[str, str] = (
            self.settings.provider_routing_config
        )
        self._provider_silence_bars_threshold: int = (
            self.settings.provider_silence_bars_threshold
        )

        # Failover state: symbol -> promoted provider (set on failover, cleared on recovery)
        self._promoted: dict[str, str] = {}

        # Last bar timestamp per provider per symbol for silence detection
        # Structure: provider -> {symbol -> last_ts}
        self._last_bar_ts: defaultdict[str, dict[str, datetime]] = defaultdict(dict)

        # Cache topic string -> provider name to avoid rsplit on every bar
        self._topic_to_provider: dict[str, str] = {
            topic_market_bars_raw(self.env_name, p): p
            for p in self._provider_raw_topics
        }

        # Instrument asset_class lookup: symbol -> asset_class string
        self._symbol_to_asset_class: dict[str, str] = {
            instr.symbol: instr.asset_class.value
            for instr in self.settings.contracts
        }

        # Pre-cache labeled metric children to avoid dict lookup on every bar
        self._routed_lbl: dict[str, object] = {}
        self._dropped_lbl: dict[str, object] = {}
        self._latency_lbl: dict[str, object] = {}
        for provider in self._provider_raw_topics:
            self._routed_lbl[provider] = MERGER_BARS_ROUTED_TOTAL.labels(
                provider=provider
            )
            self._dropped_lbl[provider] = MERGER_BARS_DROPPED_TOTAL.labels(
                provider=provider
            )
            self._latency_lbl[provider] = MERGER_BAR_LATENCY_SECONDS.labels(
                provider=provider
            )

        self._kafka_producer: KafkaProducerClient | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None

    @property
    def topics_consumed(self) -> list[str]:
        return [
            topic_market_bars_raw(self.env_name, p)
            for p in self._provider_raw_topics
        ]

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_market_bars(self.env_name),
            topic_market_data_quality(self.env_name),
        ]

    @property
    def consumer_group(self) -> str:
        """Consumer group name for process manifest and test assertions."""
        return "provider_merger_consumer"

    async def _setup(self) -> None:
        """Connect Kafka producer and consumer."""
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        raw_topics = self.topics_consumed
        self._kafka_consumer = KafkaConsumerClient(
            *raw_topics,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.consumer_group,
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "provider_merger_agent.setup_complete",
            topics_consumed=raw_topics,
            topics_produced=self.topics_produced,
            providers=self._provider_raw_topics,
        )

    async def _teardown(self) -> None:
        """Drain and close Kafka connections."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()

    async def _run(self) -> None:
        """Main loop: consume raw provider bars, route authoritative ones to market.bars."""
        assert self._kafka_consumer is not None, "Consumer not initialized — call _setup()"

        async for topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break

            try:
                bar = BarMessage.model_validate(payload)
                await self._handle_bar(topic, bar)
            except ValidationError as exc:
                await self._send_to_dlq(payload, exc)
            except Exception as exc:
                self.logger.error(
                    "provider_merger_agent.processing_error",
                    topic=topic,
                    error=str(exc),
                    payload_preview=str(payload)[:200],
                )

    async def _handle_bar(self, topic: str, bar: BarMessage) -> None:
        """Route a single bar from a raw provider topic.

        1. Extract provider from topic name.
        2. Determine authoritative provider for bar's asset_class.
        3. If authoritative (or promoted secondary): publish to market.bars + quality event.
        4. Else: update secondary tracking + check failover.
        """
        consume_ts = datetime.now(UTC)
        provider = self._topic_to_provider.get(topic) or self._extract_provider_from_topic(topic)

        # Update last_bar_ts tracking for all providers
        self._last_bar_ts[provider][bar.symbol] = bar.ts

        # Determine authoritative provider for this symbol's asset_class
        asset_class = self._symbol_to_asset_class.get(bar.symbol, "futures")
        authoritative = self._provider_routing_config.get(asset_class, self._provider_raw_topics[0])

        # Check if this symbol has a promotion (failover active)
        promoted = self._promoted.get(bar.symbol)

        # Recovery check: if primary resumes after failover
        if promoted and provider == authoritative:
            # Primary is back — clear promotion, publish recovery event
            del self._promoted[bar.symbol]
            await self._publish_quality_event(
                bar=bar,
                provider=provider,
                event_type="recovery",
                promoted_provider=authoritative,
            )
            self.logger.info(
                "provider_merger_agent.recovery",
                symbol=bar.symbol,
                provider=provider,
            )
            # Fall through to route this bar normally (primary is authoritative again)
            promoted = None

        is_authoritative = (provider == authoritative) or (promoted and provider == promoted)

        if is_authoritative:
            await self._route_bar(bar, provider, consume_ts)
        else:
            # Non-authoritative — track secondary, check failover
            lbl = self._dropped_lbl.get(provider)
            if lbl is not None:
                lbl.inc()
            await self._check_failover(bar, provider, authoritative, consume_ts)

    async def _route_bar(self, bar: BarMessage, provider: str, consume_ts: datetime) -> None:
        """Publish bar to market.bars and emit a quality event."""
        assert self._kafka_producer is not None

        publish_ts = bar.ts
        latency_s = (consume_ts - publish_ts).total_seconds()
        # Clamp to 0 to avoid negative latency from clock skew
        latency_s = max(0.0, latency_s)
        latency_ms = latency_s * 1000.0

        # Publish bar to canonical market.bars topic (source preserved unchanged)
        await self._kafka_producer.publish(
            topic_market_bars(self.env_name),
            bar.model_dump(mode="json"),
            key=message_key(bar.symbol, bar.tf),
        )

        # Metrics
        lbl = self._routed_lbl.get(provider)
        if lbl is not None:
            lbl.inc()
        lat_lbl = self._latency_lbl.get(provider)
        if lat_lbl is not None:
            lat_lbl.observe(latency_s)

        # Publish quality event (latency already computed above — pass it to avoid recompute)
        await self._publish_quality_event(
            bar=bar,
            provider=provider,
            event_type="bar_received",
            latency_ms=latency_ms,
        )

        self.logger.debug(
            "provider_merger_agent.bar_routed",
            symbol=bar.symbol,
            tf=bar.tf,
            provider=provider,
            latency_ms=round(latency_ms, 2),
        )

    async def _check_failover(
        self, bar: BarMessage, secondary_provider: str, primary_provider: str, consume_ts: datetime
    ) -> None:
        """Check if primary silence threshold exceeded; trigger failover if so."""
        symbol = bar.symbol

        # Only failover if we have seen the primary before
        primary_last = self._last_bar_ts.get(primary_provider, {}).get(symbol)
        if primary_last is None:
            # Never seen primary — don't failover
            return

        silence_seconds = (consume_ts - primary_last).total_seconds()
        bar_interval_seconds = TF_SECONDS.get(bar.tf, 60)
        threshold_seconds = self._provider_silence_bars_threshold * bar_interval_seconds

        if silence_seconds >= threshold_seconds:
            # Already promoted — skip redundant failover increment
            if self._promoted.get(symbol) == secondary_provider:
                return
            # Primary is silent — promote secondary
            self._promoted[symbol] = secondary_provider
            MERGER_FAILOVERS_TOTAL.labels(
                from_provider=primary_provider, to_provider=secondary_provider
            ).inc()
            await self._publish_quality_event(
                bar=bar,
                provider=secondary_provider,
                event_type="failover",
                promoted_provider=secondary_provider,
            )
            self.logger.warning(
                "provider_merger_agent.failover",
                symbol=symbol,
                from_provider=primary_provider,
                to_provider=secondary_provider,
                silence_seconds=round(silence_seconds, 1),
            )

    async def _publish_quality_event(
        self,
        bar: BarMessage,
        provider: str,
        event_type: Literal["bar_received", "gap_detected", "failover", "recovery"],
        latency_ms: float = 0.0,
        promoted_provider: str | None = None,
    ) -> None:
        """Serialize and publish a ProviderQualityEvent to the quality topic."""
        assert self._kafka_producer is not None

        now = datetime.now(UTC)
        event = ProviderQualityEvent(
            ts=bar.ts,
            symbol=bar.symbol,
            tf=bar.tf,
            provider=provider,
            event_type=event_type,
            publish_ts=bar.ts,
            consume_ts=now,
            latency_ms=latency_ms,
            promoted_provider=promoted_provider,
        )
        await self._kafka_producer.publish(
            topic_market_data_quality(self.env_name),
            event.model_dump(mode="json"),
            key=message_key(bar.symbol, bar.tf),
        )

    def _extract_provider_from_topic(self, topic: str) -> str:
        """Extract provider name from raw topic string.

        E.g. 'dev.market.bars.raw.ibkr' -> 'ibkr'
        """
        return topic.rsplit(".", 1)[-1]


if __name__ == "__main__":
    import asyncio

    asyncio.run(ProviderMergerAgent().start())
