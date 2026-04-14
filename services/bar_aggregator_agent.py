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

import time

from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.bar_accumulator import BarAccumulator
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.stream_keys import message_key, topic_market_bars, topic_market_bars_htf
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG


class HealthMetrics:
    """Track service health indicators for circuit breaker."""

    def __init__(self):
        self._last_bar_ts: datetime | None = None
        self._bars_last_minute = 0
        self._htf_bars_last_minute = 0
        self._bars_skipped_last_minute = 0
        self._consecutive_errors = 0
        self._last_reset = time.monotonic()
        self._last_htf_emit_ts: float = time.monotonic()  # track last HTF emission time

    def record_bar(self, bar_ts: datetime):
        """Record a successfully processed bar."""
        self._last_bar_ts = bar_ts
        self._bars_last_minute += 1

    def record_htf_bar(self):
        """Record an HTF bar emission."""
        self._htf_bars_last_minute += 1
        self._last_htf_emit_ts = time.monotonic()

    def record_error(self):
        """Record a processing error."""
        self._consecutive_errors += 1

    def reset_minute_counters(self):
        """Reset per-minute counters (called every 60s)."""
        self._bars_last_minute = 0
        self._htf_bars_last_minute = 0
        self._bars_skipped_last_minute = 0
        self._last_reset = time.monotonic()

    def record_skip(self):
        """Record a skipped bar."""
        self._bars_skipped_last_minute += 1

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

        # Check 3: Consuming but not emitting HTF bars.
        # Only flag after 7 minutes of no HTF emission — a 5m bar only closes
        # once per 5 minutes, and counters are zeroed on each consumer reset,
        # so a 30s check window will always see 0 HTF after a fresh restart.
        secs_since_htf = time.monotonic() - self._last_htf_emit_ts
        if self._bars_last_minute > 100 and secs_since_htf > 420:
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
        self._env_name: str = self.settings.env_name or ""
        super().__init__(name="bar_aggregator_agent", metrics_port=9120, max_idle_seconds=300)

        self._bar_accumulator = BarAccumulator()
        self._kafka_producer: KafkaProducerClient | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._health_metrics = HealthMetrics()
        self._last_skip_reason = "parse_failed"
        self._consumer_restart_needed = False  # Flag for consumer restart

        # Replace existing metrics with:
        self._bars_processed = Counter(
            "bar_agg_bars_processed_total", "Total 1m bars processed", ["agent"]
        )
        self._bars_skipped = Counter(
            "bar_agg_bars_skipped_total", "Bars skipped with reason", ["agent", "reason"]
        )
        self._htf_bars_emitted = Counter(
            "bar_agg_htf_bars_emitted_total", "HTF bars produced and published", ["agent", "tf"]
        )
        self._processing_duration = Histogram(
            "bar_agg_processing_duration_seconds",
            "Time to process one bar from receive to emit",
            ["agent"],
            buckets=[0.001, 0.01, 0.1, 1.0, 10.0],  # 1ms to 10s
        )
        self._aggregation_errors = Counter(
            "bar_agg_aggregation_errors_total", "Exceptions during bar processing", ["agent"]
        )
        self._health_status = Gauge(
            "bar_agg_health_status",
            "Service health status (1=healthy, 0=unhealthy)",
            ["agent"]
        )
        self._consumer_lag_seconds = Gauge(
            "bar_agg_consumer_lag_seconds",
            "How far behind the consumer is (head offset - current offset)",
            ["agent"]
        )
        self._time_since_last_bar_seconds = Gauge(
            "bar_agg_time_since_last_bar_seconds",
            "Seconds since last bar was processed",
            ["agent"]
        )
        # Add aggregation latency metric (missing from class)
        self._aggregation_latency = Histogram(
            "bar_aggregation_latency_seconds",
            "Latency for bar aggregation processing",
            ["agent"],
            buckets=[0.001, 0.01, 0.1, 1.0, 10.0]
        )
        # Add label for aggregation latency metric
        self._aggregation_latency_lbl = self._aggregation_latency.labels(agent=self.name)

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self._env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_market_bars_htf(self._env_name)]

    def _make_consumer(self) -> KafkaConsumerClient:
        """Create a fresh KafkaConsumerClient for market.bars."""
        return KafkaConsumerClient(
            topic_market_bars(self._env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="bar_aggregator_consumer",
            auto_offset_reset="latest",
        )

    async def _setup(self) -> None:
        """Connect Kafka producer and consumer with exponential-backoff retry."""
        from aiokafka.errors import KafkaConnectionError as _KCE

        _MAX_ATTEMPTS = 4   # 1 initial + 3 retries
        _BASE_DELAY = 2.0   # seconds (doubles each attempt: 2, 4, 8)

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                self._kafka_producer = KafkaProducerClient(
                    bootstrap_servers=self.settings.kafka_bootstrap_servers
                )
                await self._kafka_producer.start()

                self._kafka_consumer = self._make_consumer()
                await self._kafka_consumer.start()
                self.logger.info(
                    "bar_aggregator_agent.setup_complete",
                    topics_consumed=self.topics_consumed,
                    topics_produced=self.topics_produced,
                )
                return
            except _KCE as exc:
                # Clean up partially-started producer before retry/raise
                if self._kafka_producer is not None:
                    try:
                        await self._kafka_producer.stop()
                    except Exception:
                        pass
                    self._kafka_producer = None
                if attempt == _MAX_ATTEMPTS:
                    self.logger.error(
                        "bar_aggregator_agent.setup_failed",
                        attempt=attempt,
                        error=str(exc),
                    )
                    raise
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                self.logger.warning(
                    "bar_aggregator_agent.setup_retry",
                    attempt=attempt,
                    delay_s=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event. Stream processor — no buffer accumulation."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(0)
            await asyncio.sleep(15)

    async def _teardown(self) -> None:
        """Drain and close Kafka connections."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()

    async def _run(self) -> None:
        """Main loop: consume 1m bars, aggregate, publish completed HTF bars."""
        # Start background tasks
        health_task = asyncio.create_task(self._update_health_metrics())
        checker_task = asyncio.create_task(self._health_checker())
        lag_task = asyncio.create_task(self._report_consumer_lag())

        try:
            htf_topic = topic_market_bars_htf(self._env_name)
            last_health_log = time.monotonic()
            last_minute_reset = time.monotonic()

            # Outer loop: re-enter on consumer restart
            while self.running:
                self._consumer_restart_needed = False
                async for _topic, _key, payload in self._kafka_consumer.messages():
                    if not self.running or self._consumer_restart_needed:
                        break

                    # Reset minute counters every 60 seconds
                    if time.monotonic() - last_minute_reset > 60:
                        self._health_metrics.reset_minute_counters()
                        last_minute_reset = time.monotonic()

                    # Log health summary every 60 seconds
                    if time.monotonic() - last_health_log > 60:
                        healthy, reason = self._health_metrics.is_healthy()
                        lag = await self._get_consumer_lag()

                        self.logger.info(
                            "bar_aggregator_health",
                            healthy=healthy,
                            reason=reason,
                            processed_last_min=self._health_metrics._bars_last_minute,
                            skipped_last_min=self._health_metrics._bars_skipped_last_minute,
                            htf_emitted_last_min=self._health_metrics._htf_bars_last_minute,
                            consumer_lag=lag,
                        )
                        last_health_log = time.monotonic()

                    # NEW: Timeout protection for each bar
                    try:
                        async with asyncio.timeout(5.0):  # Max 5 seconds per bar
                            start_time = time.monotonic()

                            # Parse and process bar
                            bar = self._parse_bar(payload)
                            if bar is None:
                                self._bars_skipped.labels(
                                    agent=self.name, reason=self._last_skip_reason
                                ).inc()
                                self._health_metrics.record_skip()
                                continue

                            # Track liveness for stall detection (Phase 067-06)
                            self._record_message_consumed()

                            self._health_metrics.record_bar(bar.ts)

                            self._bars_processed.labels(agent=self.name).inc()

                            with self._processing_duration.labels(agent=self.name).time():
                                completed_bars = self._bar_accumulator.update(bar)

                            # Emit HTF bars
                            for htf_bar in completed_bars:
                                await self._kafka_producer.publish(
                                    htf_topic,
                                    htf_bar.model_dump(mode="json"),
                                    key=message_key(htf_bar.symbol, htf_bar.tf),
                                )
                                self._htf_bars_emitted.labels(agent=self.name, tf=htf_bar.tf).inc()
                                self._health_metrics.record_htf_bar()
                                self.logger.debug(
                                    "bar_aggregator_agent.htf_bar_published",
                                    symbol=htf_bar.symbol,
                                    tf=htf_bar.tf,
                                    ts=htf_bar.ts.isoformat(),
                                )

                            # Check for slow processing
                            duration = time.monotonic() - start_time
                            if duration > 1.0:
                                self.logger.warning(
                                    "bar_aggregator.slow_bar_processing",
                                    symbol=bar.symbol,
                                    duration_s=duration,
                                    htf_emitted=len(completed_bars),
                                )

                    except TimeoutError:
                        # Handle timeout for slow bar processing
                        self._aggregation_errors.labels(agent=self.name).inc()
                        self.logger.error(
                            "bar_aggregator.processing_timeout",
                            symbol=payload.get("symbol", "unknown"),
                            ts=payload.get("ts") or payload.get("timestamp"),
                            timeout_seconds=5
                        )
                        # Continue to next bar - don't let one slow bar block everything

                    except Exception as exc:
                        # Handle other exceptions during bar processing
                        self._health_metrics.record_error()
                        self._aggregation_errors.labels(agent=self.name).inc()
                        self.logger.error(
                            "bar_aggregator.processing_error",
                            error=str(exc),
                            payload_preview=str(payload)[:200],
                        )
                        # Don't crash on single bar failure — continue consuming

                # Consumer restart — recreate consumer object to avoid aiokafka
                # "Did you call start twice?" error on stop()+start() of same instance.
                if self._consumer_restart_needed and self.running:
                    try:
                        await self._kafka_consumer.stop()
                        await asyncio.sleep(1)
                        self._kafka_consumer = self._make_consumer()
                        await self._kafka_consumer.start()
                        self._health_metrics._consecutive_errors = 0
                        self._health_metrics._bars_last_minute = 0
                        self._health_metrics._htf_bars_last_minute = 0
                        self._health_metrics._last_htf_emit_ts = time.monotonic()
                        self.logger.info("bar_aggregator.consumer_reset_complete")
                    except Exception as exc:
                        self.logger.error(
                            "bar_aggregator.consumer_reset_failed", error=str(exc)
                        )
                        raise  # unrecoverable — let systemd restart clean

        finally:
            health_task.cancel()
            checker_task.cancel()
            lag_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
            try:
                await checker_task
            except asyncio.CancelledError:
                pass
            try:
                await lag_task
            except asyncio.CancelledError:
                pass

    async def _update_health_metrics(self):
        """Update Prometheus health metrics every 15 seconds."""
        while self.running:
            healthy, _ = self._health_metrics.is_healthy()
            self._health_status.labels(agent=self.name).set(1 if healthy else 0)

            lag = await self._get_consumer_lag()
            self._consumer_lag_seconds.labels(agent=self.name).set(lag)

            # Update time_since_last_bar (only if we've processed bars; None means never processed)
            if self._health_metrics._last_bar_ts:
                time_since = (datetime.now(UTC) - self._health_metrics._last_bar_ts).total_seconds()
                self._time_since_last_bar_seconds.labels(agent=self.name).set(time_since)
            # When _last_bar_ts is None, metric remains at 0 (never processed)

            await asyncio.sleep(15)

    async def _health_checker(self):
        """Background task: monitor health and take action."""
        while self.running:
            await asyncio.sleep(30)  # Check every 30 seconds

            healthy, reason = self._health_metrics.is_healthy()

            if not healthy:
                self.logger.error(
                    "bar_aggregator.unhealthy",
                    reason=reason,
                    bars_last_min=self._health_metrics._bars_last_minute,
                    htf_last_min=self._health_metrics._htf_bars_last_minute,
                    consecutive_errors=self._health_metrics._consecutive_errors,
                    last_bar=(
                        self._health_metrics._last_bar_ts.isoformat()
                        if self._health_metrics._last_bar_ts
                        else None
                    ),
                )

                # HEALTH CHECK FAILED - take action
                await self._handle_unhealthy_state(reason)

    async def _handle_unhealthy_state(self, reason: str):
        """Signal main loop to restart consumer. Stop/start is the outer loop's job."""
        if "no_bars" in reason or "consuming_not_emitting" in reason:
            self.logger.warning("bar_aggregator.attempting_consumer_reset")
            self._consumer_restart_needed = True

    async def _get_consumer_lag(self) -> int:
        """Get current consumer lag in seconds."""
        try:
            # This is expensive - only call for health summaries
            import aiokafka

            consumer = aiokafka.AIOKafkaConsumer(
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                group_id="bar_aggregator_consumer",
            )
            await consumer.start()

            inner = getattr(self._kafka_consumer, "_consumer", None)
            if inner is None:
                await consumer.stop()
                return 0
            partitions = inner.assignment()
            if not partitions:
                await consumer.stop()
                return 0

            tp = next(iter(partitions))
            end_offsets = await consumer.end_offsets([tp])
            position = await inner.position(tp)

            await consumer.stop()
            return end_offsets[tp] - position if end_offsets[tp] >= position else 0
        except Exception:
            return 0  # Assume healthy if lag check fails

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
            self._last_skip_reason = "validation_error"
            pass

        # Legacy / flat dict format from DataProviderAgent
        try:
            symbol = payload.get("symbol", "")
            tf = payload.get("tf") or payload.get("timeframe", "1m")
            if not symbol or not tf:
                self._last_skip_reason = "missing_symbol_or_tf"
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
            self._last_skip_reason = "parse_exception"
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

    setup_service_logging("logs/bar_aggregator_agent.log")
    asyncio.run(main())
