#!/usr/bin/env python3
"""BarAggregator — standalone 1m->HTF bar aggregation.

Consumes 1m bars from topic_market_bars, runs BarAccumulator,
publishes completed HTF bars to topic_market_bars_htf.

DB-ignorant ComputeAgent — no database access.

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
import time
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
from opentelemetry import metrics as _otel_metrics
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# OTel metrics — module-level constants (single registration per process)
# ---------------------------------------------------------------------------

_baa_meter = _otel_metrics.get_meter("indicagent")

_BARS_PROCESSED = _baa_meter.create_counter(
    "bar_agg_bars_processed_total", description="Total 1m bars processed"
)
_BARS_SKIPPED = _baa_meter.create_counter(
    "bar_agg_bars_skipped_total", description="Bars skipped with reason"
)
_HTF_BARS_EMITTED = _baa_meter.create_counter(
    "bar_agg_htf_bars_emitted_total", description="HTF bars produced and published"
)
_PROCESSING_DURATION = _baa_meter.create_histogram(
    "bar_agg_processing_duration_seconds",
    description="Time to process one bar from receive to emit",
)
_AGGREGATION_ERRORS = _baa_meter.create_counter(
    "bar_agg_aggregation_errors_total", description="Exceptions during bar processing"
)
_HEALTH_STATUS = _baa_meter.create_gauge(
    "bar_agg_health_status", description="Service health status (1=healthy, 0=unhealthy)"
)
_CONSUMER_LAG_SECONDS = _baa_meter.create_gauge(
    "bar_agg_consumer_lag_seconds", description="Committed offset lag (messages behind log end)"
)
_TIME_SINCE_LAST_BAR_SECONDS = _baa_meter.create_gauge(
    "bar_agg_time_since_last_bar_seconds", description="Seconds since last bar was processed"
)
_AGGREGATION_LATENCY = _baa_meter.create_histogram(
    "bar_aggregation_latency_seconds", description="Latency for bar aggregation processing"
)
_BARS_IN_FLIGHT = _baa_meter.create_up_down_counter(
    "bar_aggregator_bars_in_flight",
    description="Approximate number of bars currently being processed",
)
_STATE_CHECKPOINT_RESTORED_TOTAL = _baa_meter.create_counter(
    "bar_aggregator_state_checkpoint_restored_total",
    description="State checkpoint successful restores",
)
_STATE_CHECKPOINT_FAILURES_TOTAL = _baa_meter.create_counter(
    "bar_aggregator_state_checkpoint_failures_total",
    description="State checkpoint encode/decode failures",
)

from src.core.agent.base import BaseDaemon
from src.core.bar_accumulator import BarAccumulator
from src.core.bar_normalizer import SOURCE_UNKNOWN
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.stream_keys import (
    message_key,
    topic_bar_aggregator_dlq,
    topic_bar_aggregator_state,  # Phase 74: state checkpointing
    topic_market_bars,
    topic_market_bars_htf,
)


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


class BarAggregator(BaseDaemon):
    """DB-ignorant bar aggregation agent.

    Consumes 1m bars from topic_market_bars, accumulates them per
    (symbol, tf) via BarAccumulator, and publishes completed HTF bars
    to topic_market_bars_htf on period boundaries.

    No DB reads or writes — pure streaming compute (D-11, D-13).
    Cold-start: auto.offset.reset=latest (D-14).
    """

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=300)
        self._bar_accumulator = BarAccumulator()
        self._kafka_producer: KafkaProducerClient | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None
        self._lag_consumer = None  # AGG-AUDIT-LOW-6: cached lag check consumer
        self._health_metrics = HealthMetrics()
        self._last_skip_reason = "parse_failed"
        self._consumer_restart_needed = False  # Flag for consumer restart
        # AGG-EMIT-ONCE: tracks last emitted period_ts per (symbol, tf) to suppress duplicates
        self._last_emitted: dict[tuple[str, str], datetime] = {}
        # AGG-BACKPRESSURE: cap concurrent bar processing to prevent unbounded memory on burst
        self._processing_semaphore = asyncio.Semaphore(200)
        self._AGENT_VERSION = "1"
        self._agent_attrs = {"agent": self.name}
        # Degradation detection: track recent checkpoint failure timestamps
        self._checkpoint_failure_timestamps: list[float] = []

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self.env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_market_bars_htf(self.env_name)]

    def _dlq_topic(self) -> str | None:
        return topic_bar_aggregator_dlq(self.env_name)

    def _make_consumer(self) -> KafkaConsumerClient:
        """Create a fresh KafkaConsumerClient for market.bars."""
        return KafkaConsumerClient(
            topic_market_bars(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="bar_aggregator_consumer",
            auto_offset_reset="latest",
        )

    async def _setup(self) -> None:
        """Connect Kafka producer and consumer (single attempt — retries handled by BaseDaemon._setup_with_retry)."""
        import confluent_kafka

        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()

        self._kafka_consumer = self._make_consumer()
        await self._kafka_consumer.start()

        # AGG-AUDIT-LOW-6: cache the lag check consumer instead of creating per-call.
        # Not subscribed to anything — used purely for committed()/get_watermark_offsets()
        # queries against the shared "bar_aggregator_consumer" group in _get_consumer_lag().
        self._lag_consumer = confluent_kafka.Consumer(
            {
                "bootstrap.servers": self.settings.kafka_bootstrap_servers,
                "group.id": "bar_aggregator_consumer",
            }
        )

        # Restore state from checkpoint topic
        restored = await self._restore_state_checkpoint()
        if not restored:
            self.logger.info("bar_aggregator.state.checkpoint_miss — starting fresh")

        self.logger.info(
            "bar_aggregator.setup_complete",
            topics_consumed=self.topics_consumed,
            topics_produced=self.topics_produced,
        )

    def _track_checkpoint_failure(self) -> bool:
        """Track checkpoint failures in sliding window. Return True if degraded.

        Degradation threshold: 3 failures within 60 seconds → stop processing.
        This prevents silent data loss when checkpointing is broken.
        """
        now = time.monotonic()
        # Add current failure
        self._checkpoint_failure_timestamps.append(now)
        # Prune old failures (outside 60s window)
        self._checkpoint_failure_timestamps = [
            ts for ts in self._checkpoint_failure_timestamps if now - ts < 60.0
        ]
        # Check if degraded
        if len(self._checkpoint_failure_timestamps) >= 3:
            self.logger.error(
                "bar_aggregator.checkpoint_degraded",
                failures=len(self._checkpoint_failure_timestamps),
                window_60s=True,
            )
            return True  # Degraded — stop processing
        return False  # OK to continue

    async def _restore_state_checkpoint(self) -> bool:
        """Consume compacted state topic and restore BarAccumulator state."""
        state_topic = topic_bar_aggregator_state(self.settings.env_name)
        consumer = None
        try:
            consumer = KafkaConsumerClient(
                state_topic,
                bootstrap_servers=self.settings.kafka_bootstrap_servers,
                group_id="bar_aggregator_state_restore",
                auto_offset_reset="earliest",
            )
            await consumer.start()

            result: list[bool] = [False]

            async def _drain() -> None:
                async for _topic, key_str, payload in consumer.messages():
                    if not key_str:
                        continue
                    if not isinstance(payload, dict):
                        continue

                    parts = key_str.split(":")
                    if len(parts) != 3:
                        self.logger.warning("state.invalid_key_format", key=key_str)
                        continue
                    version, symbol, tf = parts
                    if version != self._AGENT_VERSION:
                        self.logger.warning(
                            "state.version_mismatch",
                            key=key_str,
                            version=version,
                            expected=self._AGENT_VERSION,
                        )
                        continue

                    if "_accumulators" in payload:
                        for k, v in payload["_accumulators"].items():
                            self._bar_accumulator._accumulators[k] = v
                    if "_last_session_boundary_log" in payload:
                        for k, v in payload["_last_session_boundary_log"].items():
                            self._bar_accumulator._last_session_boundary_log[k] = v
                    result[0] = True

            try:
                await asyncio.wait_for(_drain(), timeout=5.0)
            except TimeoutError:
                pass  # normal — drained all available messages

            restored_any = result[0]
            if restored_any:
                _STATE_CHECKPOINT_RESTORED_TOTAL.add(1)
                self.logger.info(
                    "bar_aggregator.state.restored",
                    accumulators=len(self._bar_accumulator._accumulators),
                )

            return restored_any

        except Exception as error:
            self.logger.warning("bar_aggregator.state.restore_failed", error=str(error))
            _STATE_CHECKPOINT_FAILURES_TOTAL.add(1)
            return False
        finally:
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass

    async def _checkpoint_state(self, bar: BarMessage) -> None:
        """Encode BarAccumulator state and enqueue to compacted state topic."""
        state = {
            "_accumulators": self._bar_accumulator._accumulators,
            "_last_session_boundary_log": self._bar_accumulator._last_session_boundary_log,
        }
        checkpoint_key = f"{self._AGENT_VERSION}:{bar.symbol}:{bar.tf}"
        await self._kafka_producer.publish(
            topic_bar_aggregator_state(self.settings.env_name),
            state,
            checkpoint_key,
        )

    async def _teardown(self) -> None:
        """Drain and close Kafka connections."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._lag_consumer is not None:
            try:
                await asyncio.to_thread(self._lag_consumer.close)
            except Exception:
                pass

    async def _run(self) -> None:
        """Main loop: consume 1m bars, aggregate, publish completed HTF bars."""
        # Start background tasks (lag_task created by BaseDaemon.start() at line 155)
        health_task = asyncio.create_task(self._update_health_metrics())
        checker_task = asyncio.create_task(self._health_checker())

        try:
            htf_topic = topic_market_bars_htf(self.env_name)
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

                    # AGG-BACKPRESSURE: cap concurrent in-flight bar processing.
                    # Semaphore is saturated when all 200 slots are taken — pause
                    # consumption 100ms to let the event loop drain pending work.
                    if self._processing_semaphore.locked():
                        self.logger.warning(
                            "bar_aggregator.semaphore_saturated",
                            semaphore_value=self._processing_semaphore._value,
                        )
                        await asyncio.sleep(0.1)

                    # NEW: Timeout protection for each bar (wrapped in semaphore)
                    try:
                        async with self._processing_semaphore:
                            _BARS_IN_FLIGHT.add(200 - self._processing_semaphore._value)
                            async with asyncio.timeout(5.0):  # Max 5 seconds per bar
                                start_time = time.monotonic()

                                # Parse and process bar
                                bar = self._parse_bar(payload)
                                if bar is None:
                                    _BARS_SKIPPED.add(
                                        1, {"agent": self.name, "reason": self._last_skip_reason}
                                    )
                                    self._health_metrics.record_skip()
                                    # AGG-DLQ: route malformed payload to DLQ instead of silent drop
                                    await self._send_to_dlq(
                                        payload if isinstance(payload, dict) else {},
                                        ValueError(f"bar_parse_failed:{self._last_skip_reason}"),
                                    )
                                    continue

                                # Track liveness for stall detection (Phase 067-06)
                                self._record_message_consumed()

                                self._health_metrics.record_bar(bar.ts)

                                _BARS_PROCESSED.add(1, self._agent_attrs)

                                _pd_t0 = time.monotonic()
                                completed_bars = self._bar_accumulator.update(bar)
                                _PROCESSING_DURATION.record(
                                    time.monotonic() - _pd_t0, self._agent_attrs
                                )

                                # Emit HTF bars with emit-once guard (AGG-EMIT-ONCE)
                                for htf_bar in completed_bars:
                                    emit_key = (htf_bar.symbol, htf_bar.tf)
                                    if self._last_emitted.get(emit_key) == htf_bar.ts:
                                        self.logger.warning(
                                            "htf_duplicate_suppressed",
                                            symbol=htf_bar.symbol,
                                            tf=htf_bar.tf,
                                            period_ts=htf_bar.ts.isoformat(),
                                        )
                                        continue
                                    self._last_emitted[emit_key] = htf_bar.ts
                                    await self._kafka_producer.publish(
                                        htf_topic,
                                        htf_bar.model_dump(mode="json"),
                                        key=message_key(htf_bar.symbol, htf_bar.tf),
                                    )
                                    _HTF_BARS_EMITTED.add(1, {"agent": self.name, "tf": htf_bar.tf})
                                    self._health_metrics.record_htf_bar()
                                    self.logger.debug(
                                        "bar_aggregator.htf_bar_published",
                                        symbol=htf_bar.symbol,
                                        tf=htf_bar.tf,
                                        ts=htf_bar.ts.isoformat(),
                                    )

                                try:
                                    await self._checkpoint_state(bar)
                                    self._checkpoint_failure_timestamps.clear()
                                except Exception as error:
                                    self.logger.warning(
                                        "bar_aggregator.checkpoint_failed", error=str(error)
                                    )
                                    _STATE_CHECKPOINT_FAILURES_TOTAL.add(1)
                                    # Check if degraded (3 failures in 60s)
                                    if self._track_checkpoint_failure():
                                        # Degraded — stop processing to prevent data loss/corruption
                                        self.logger.critical(
                                            "bar_aggregator.stop_processing_degraded",
                                            reason="checkpoint_failed_repeatedly",
                                            failure_count=len(self._checkpoint_failure_timestamps),
                                        )
                                        raise  # Stop the agent — systemd will restart

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
                        _AGGREGATION_ERRORS.add(1, self._agent_attrs)
                        self.logger.error(
                            "bar_aggregator.processing_timeout",
                            symbol=payload.get("symbol", "unknown"),
                            ts=payload.get("ts") or payload.get("timestamp"),
                            timeout_seconds=5,
                        )
                        # Continue to next bar - don't let one slow bar block everything

                    except Exception as error:
                        # Handle other exceptions during bar processing
                        self._health_metrics.record_error()
                        _AGGREGATION_ERRORS.add(1, self._agent_attrs)
                        self.logger.error(
                            "bar_aggregator.processing_error",
                            error=str(error),
                            payload_preview=str(payload)[:200],
                        )
                        # Don't crash on single bar failure — continue consuming

                # Consumer restart — recreate consumer object; a closed
                # confluent_kafka.Consumer cannot be reused after close().
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
                    except Exception as error:
                        self.logger.error("bar_aggregator.consumer_reset_failed", error=str(error))
                        raise  # unrecoverable — let systemd restart clean

        finally:
            health_task.cancel()
            checker_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
            try:
                await checker_task
            except asyncio.CancelledError:
                pass

    async def _update_health_metrics(self):
        """Update health metrics every 15 seconds."""
        while self.running:
            healthy, _ = self._health_metrics.is_healthy()
            _HEALTH_STATUS.set(1 if healthy else 0, self._agent_attrs)

            lag = await self._get_consumer_lag()
            _CONSUMER_LAG_SECONDS.set(lag, self._agent_attrs)

            if self._health_metrics._last_bar_ts:
                time_since = (datetime.now(UTC) - self._health_metrics._last_bar_ts).total_seconds()
                _TIME_SINCE_LAST_BAR_SECONDS.set(time_since, self._agent_attrs)

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
        """Get current consumer lag using committed offsets vs log end offset.

        Uses committed offset (matches rpk group describe) rather than the
        librdkafka internal fetch position, which can diverge from committed state.
        """
        try:
            inner = getattr(self._kafka_consumer, "_consumer", None)
            if inner is None or self._lag_consumer is None:
                return 0
            partitions = await asyncio.to_thread(inner.assignment)
            if not partitions:
                return 0

            tp = partitions[0]
            _low, high = await asyncio.to_thread(
                self._lag_consumer.get_watermark_offsets, tp, timeout=10.0
            )
            committed_list = await asyncio.to_thread(self._lag_consumer.committed, [tp], 10.0)
            if not committed_list or committed_list[0].offset < 0:
                return 0

            return max(0, high - committed_list[0].offset)
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
            if not ts_raw:
                self._last_skip_reason = "missing_timestamp"
                return None  # route to DLQ — never fabricate a timestamp
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            return BarMessage(
                ts=ts,
                symbol=symbol,
                tf=tf,
                open=float(payload.get("open", 0)),
                high=float(payload.get("high", 0)),
                low=float(payload.get("low", 0)),
                close=float(payload.get("close", 0)),
                volume=int(float(payload.get("volume", 0))),
                source=payload.get("source", SOURCE_UNKNOWN),
                session_type=SessionType(payload.get("session_type", "rth")),
                gap_preceding=bool(payload.get("gap_preceding", False)),
                is_flat_bar=bool(payload.get("is_flat_bar", False)),
            )
        except Exception as error:
            self._last_skip_reason = "parse_exception"
            self.logger.warning(
                "bar_aggregator.parse_failed",
                error=str(error),
                payload_preview=str(payload)[:200],
            )
            return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    agent = BarAggregator()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
