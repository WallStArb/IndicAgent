#!/usr/bin/env python3
"""BarAggregatorComputeAgent — standalone 1m->HTF bar aggregation.

Consumes 1m bars from topic_market_bars, runs BarAccumulator,
publishes completed HTF bars to topic_market_bars_htf.

DB-ignorant ComputeAgent — no database access.
Metrics port: :9120

Golden Signals (D-16):
- Traffic: events_consumed_total, htf_bars_produced_total{tf}
- Latency: bar_aggregation_latency_seconds
- Errors: aggregation_errors_total

Version: 1.0.0
Last Updated: 2026-03-28
Status: Phase 053.2 Plan 02
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from prometheus_client import Counter, Histogram

import time

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.bar_accumulator import BarAccumulator
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.stream_keys import message_key, topic_market_bars, topic_market_bars_htf


class HealthMetrics:
    """Track service health indicators for circuit breaker."""

    def __init__(self):
        self._last_bar_ts: datetime | None = None
        self._bars_last_minute = 0
        self._htf_bars_last_minute = 0
        self._consecutive_errors = 0
        self._last_reset = time.monotonic()

    def record_bar(self, bar_ts: datetime):
        """Record a successfully processed bar."""
        self._last_bar_ts = bar_ts
        self._bars_last_minute += 1

    def record_htf_bar(self):
        """Record an HTF bar emission."""
        self._htf_bars_last_minute += 1

    def record_error(self):
        """Record a processing error."""
        self._consecutive_errors += 1

    def reset_minute_counters(self):
        """Reset per-minute counters (called every 60s)."""
        self._bars_last_minute = 0
        self._htf_bars_last_minute = 0
        self._last_reset = time.monotonic()

    def is_healthy(self) -> tuple[bool, str]:
        """Check if service is healthy. Returns (healthy, reason)."""
        now = datetime.now(UTC)

        # Check 1: Processing bars
        if self._last_bar_ts is None:
            return False, "never_processed"

        time_since_last_bar = (now - self._last_bar_ts).total_seconds()
        if time_since_last_bar > 300:  # 5 minutes with no bars
            return False, f"no_bars_{int(time_since_last_bar)}s"

        # Check 2: Too many errors
        if self._consecutive_errors > 50:
            return False, f"consecutive_errors_{self._consecutive_errors}"

        # Check 3: Consuming but not emitting HTF bars
        if self._bars_last_minute > 100 and self._htf_bars_last_minute == 0:
            return False, "consuming_not_emitting"

        return True, "healthy"


class BarAggregatorComputeAgent(BaseAgent):
    """DB-ignorant bar aggregation agent.

    Consumes 1m bars from topic_market_bars, accumulates them per
    (symbol, tf) via BarAccumulator, and publishes completed HTF bars
    to topic_market_bars_htf on period boundaries.

    No DB reads or writes — pure streaming compute (D-11, D-13).
    Cold-start: auto.offset.reset=latest (D-14).
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="bar_aggregator_agent", metrics_port=9120)

        self._bar_accumulator = BarAccumulator()
        self._kafka_producer: KafkaProducerClient | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._health_metrics = HealthMetrics()

        # Replace existing metrics with:
        self._bars_processed = Counter(
            "bar_agg_bars_processed_total",
            "Total 1m bars processed",
            ["agent"]
        )
        self._bars_skipped = Counter(
            "bar_agg_bars_skipped_total",
            "Bars skipped with reason",
            ["agent", "reason"]
        )
        self._htf_bars_emitted = Counter(
            "bar_agg_htf_bars_emitted_total",
            "HTF bars produced and published",
            ["agent", "tf"]
        )
        self._processing_duration = Histogram(
            "bar_agg_processing_duration_seconds",
            "Time to process one bar from receive to emit",
            ["agent"],
            buckets=[0.001, 0.01, 0.1, 1.0, 10.0]  # 1ms to 10s
        )
        self._aggregation_errors = Counter(
            "bar_agg_aggregation_errors_total",
            "Exceptions during bar processing",
            ["agent"]
        )

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self._env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_market_bars_htf(self._env_name)]

    async def _setup(self) -> None:
        """Connect Kafka producer and consumer."""
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._kafka_consumer = KafkaConsumerClient(
            topic_market_bars(self._env_name),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="bar_aggregator_consumer",
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "bar_aggregator_agent.setup_complete",
            topics_consumed=self.topics_consumed,
            topics_produced=self.topics_produced,
        )

    async def _teardown(self) -> None:
        """Drain and close Kafka connections."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()

    async def _run(self) -> None:
        """Main loop: consume 1m bars, aggregate, publish completed HTF bars."""
        htf_topic = topic_market_bars_htf(self._env_name)

        async for _topic, _key, payload in self._kafka_consumer.messages():
            if not self.running:
                break

            try:
                bar = self._parse_bar(payload)
                if bar is None:
                    continue

                self._bars_processed.labels(agent=self.name).inc()

                with self._processing_duration.labels(agent=self.name).time():
                    completed_bars = self._bar_accumulator.update(bar)

                for htf_bar in completed_bars:
                    await self._kafka_producer.publish(
                        htf_topic,
                        htf_bar.model_dump(mode="json"),
                        key=message_key(htf_bar.symbol, htf_bar.tf),
                    )
                    self._htf_bars_emitted.labels(agent=self.name, tf=htf_bar.tf).inc()
                    self.logger.debug(
                        "bar_aggregator_agent.htf_bar_published",
                        symbol=htf_bar.symbol,
                        tf=htf_bar.tf,
                        ts=htf_bar.ts.isoformat(),
                    )

            except Exception as exc:
                self._aggregation_errors.labels(agent=self.name).inc()
                self.logger.error(
                    "bar_aggregator_agent.processing_error",
                    error=str(exc),
                    payload_preview=str(payload)[:200],
                )
                # Don't crash on single bar failure — continue consuming

    def _parse_bar(self, payload: dict) -> BarMessage | None:
        """Parse a bar payload dict from Kafka into a typed BarMessage.

        Tries model_validate first (canonical BarMessage dict from BarAccumulator
        or recent producers). Falls back to manual field extraction for legacy
        DataProviderAgent format where OHLCV fields may be strings or use
        'timestamp' / 'timeframe' key names.

        Returns None when the payload cannot be parsed — caller skips the bar.
        """
        try:
            return BarMessage.model_validate(payload)
        except ValidationError:
            pass

        # Legacy / flat dict format from DataProviderAgent
        try:
            symbol = payload.get("symbol", "")
            tf = payload.get("tf") or payload.get("timeframe", "1m")
            if not symbol or not tf:
                return None

            ts_raw = payload.get("ts") or payload.get("timestamp")
            if ts_raw:
                ts = datetime.fromisoformat(str(ts_raw))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            else:
                ts = datetime.now(UTC)

            return BarMessage(
                ts=ts,
                symbol=symbol,
                tf=tf,
                open=float(payload.get("open", 0)),
                high=float(payload.get("high", 0)),
                low=float(payload.get("low", 0)),
                close=float(payload.get("close", 0)),
                volume=int(float(payload.get("volume", 0))),
                source=payload.get("source", "ibkr_named"),
                session_type=SessionType(payload.get("session_type", "rth")),
                gap_preceding=bool(payload.get("gap_preceding", False)),
                is_flat_bar=bool(payload.get("is_flat_bar", False)),
            )
        except Exception as exc:
            self.logger.warning(
                "bar_aggregator_agent.parse_failed",
                error=str(exc),
                payload_preview=str(payload)[:200],
            )
            return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = BarAggregatorComputeAgent()
    await agent.start()


if __name__ == "__main__":
    from src.core.service_utils import setup_service_logging
    from src.observability.otel import init_tracing

    setup_service_logging("logs/bar_aggregator_agent.log")
    init_tracing("bar_aggregator_agent")
    asyncio.run(main())
