"""BaseWriterAgent — abstract base for all Kafka-to-DB writer agents.

Provides the standard buffer/flush/commit/overflow/teardown pattern shared by
all writer agents, while leaving the Kafka consumption loop to each subclass.

Write-path reliability guarantees:
- Manual offset commit (only after successful _flush_batch)
- DLQ routing for unparseable payloads
- Bounded buffer with overflow metric
- Buffer depth Prometheus gauge
- Final flush on teardown

Subclasses implement:
- _topic_name() -> str: Kafka topic to consume from
- _consumer_group -> str: Kafka consumer group ID
- _parse_payload(payload) -> list | None: Parse raw Kafka payload into rows
- _flush_batch(batch) -> None: Write batch to database

Optionally override:
- _dlq_topic() -> str | None: DLQ topic name (None = log-only, default)
"""

from __future__ import annotations

import abc
import asyncio
import time
from typing import Any

from prometheus_client import Counter as _Counter
from prometheus_client import Gauge as _Gauge
from prometheus_client import Histogram as _Histogram

from src.core.agent.base import BaseAgent
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG

# Module-level metric caches — prevent duplicate registration across
# multiple instantiations in the same process (e.g., unit tests).
_gauges: dict[str, _Gauge] = {}
_counters: dict[str, _Counter] = {}
_histograms: dict[str, _Histogram] = {}


def _get_or_create_gauge(name: str, doc: str) -> _Gauge:
    if name not in _gauges:
        _gauges[name] = _Gauge(name, doc)
    return _gauges[name]


def _get_or_create_counter(name: str, doc: str) -> _Counter:
    if name not in _counters:
        _counters[name] = _Counter(name, doc)
    return _counters[name]


def _get_or_create_histogram(name: str, doc: str, buckets: list[float]) -> _Histogram:
    if name not in _histograms:
        _histograms[name] = _Histogram(name, doc, buckets=buckets)
    return _histograms[name]


class BaseWriterAgent(BaseAgent, abc.ABC):
    """Abstract base for writer agents that consume Kafka and write to DB.

    Provides the shared buffer/flush/commit/overflow/teardown pattern plus a
    default _run() consume loop. Subclasses that need custom routing (e.g.
    multi-topic dispatch) should override _run(); most can rely on the default.

    Use _create_consumer() in _setup() to eliminate manual consumer wiring.

    Lifecycle:
        _setup() → _create_consumer() + DB init
        _run() → consume loop calling _buffer_rows() / maybe_flush()
        _teardown() → _do_flush() (final flush) → subclass cleanup
    """

    BATCH_SIZE: int = 100
    FLUSH_INTERVAL_SECS: float = 5.0
    MAX_BUFFER_SIZE: int = 10_000
    BUFFER_ALERT_PCT: float = 0.80

    def __init__(
        self,
        name: str,
        metrics_port: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, metrics_port=metrics_port, **kwargs)
        self._buffer: list[Any] = []
        self._last_flush: float = 0.0
        self._consumer: Any = None  # Set in subclass _setup() — MUST be assigned for offset commits
        self._high_watermark_triggered: bool = False

        # Precomputed thresholds (constants for lifetime — avoid per-message float math)
        self._overflow_threshold: int = self.MAX_BUFFER_SIZE
        self._alert_threshold: float = self.BUFFER_ALERT_PCT * self.MAX_BUFFER_SIZE

        # Metrics — safe registration via module-level cache (test safety)
        agent_snake = name.lower().replace(" ", "_")
        self._buffer_depth_gauge = _get_or_create_gauge(
            f"{agent_snake}_buffer_depth",
            f"Current buffer depth for {name}",
        )
        self._buffer_overflow_total = _get_or_create_counter(
            f"{agent_snake}_buffer_overflow_total",
            f"Rows dropped due to buffer overflow in {name}",
        )

        # Write-path observability metrics
        self._flush_latency = _get_or_create_histogram(
            f"{agent_snake}_flush_latency_seconds",
            f"DB batch write latency for {name}",
            [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        )
        self._commit_latency = _get_or_create_histogram(
            f"{agent_snake}_commit_latency_seconds",
            f"Kafka offset commit latency for {name}",
            [0.0001, 0.001, 0.005, 0.01, 0.05, 0.1],
        )
        self._parse_failures_total = _get_or_create_counter(
            f"{agent_snake}_parse_failures_total",
            f"Payload parse failures (routed to DLQ) in {name}",
        )
        self._flush_errors_total = _get_or_create_counter(
            f"{agent_snake}_flush_errors_total",
            f"Batch flush failures in {name}",
        )
        self._commit_errors_total = _get_or_create_counter(
            f"{agent_snake}_commit_errors_total",
            f"Offset commit failures in {name}",
        )

    @abc.abstractmethod
    def _topic_name(self) -> str:
        """Kafka topic to consume from."""

    @property
    @abc.abstractmethod
    def _consumer_group(self) -> str:
        """Kafka consumer group ID."""

    @abc.abstractmethod
    def _parse_payload(self, payload: dict) -> list | None:
        """Parse raw Kafka payload into rows for buffer.

        Return list of parsed rows to buffer, or None to route to DLQ.
        """

    @abc.abstractmethod
    async def _flush_batch(self, batch: list) -> None:
        """Write batch to database. Must NOT clear self._buffer — caller handles that."""

    def _dlq_topic(self) -> str | None:
        """Override to return DLQ topic name. None = log-only (default)."""
        return None

    def _create_consumer(self, topics: list[str] | None = None) -> Any:
        """Create and start a KafkaConsumerClient assigned to self._consumer.

        Subclasses call this in _setup() instead of manually constructing consumers.
        Accepts optional extra topics for multi-topic consumers (e.g. bar_writer).
        """
        from src.core.kafka_utils import KafkaConsumerClient

        topic_list = topics or [self._topic_name()]
        consumer = KafkaConsumerClient(
            *topic_list,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self._consumer_group,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        self._consumer = consumer
        return consumer

    async def _maybe_route_to_dlq(self, payload: dict, error: Exception) -> None:
        """Route payload to DLQ if _dlq_topic() is configured.

        Call from _run() when _parse_payload() returns None.
        Delegates to BaseAgent._send_to_dlq() which handles DLQ routing and metrics.
        """
        await self._send_to_dlq(payload, error)

    # -----------------------------------------------------------------------
    # Buffer management — called from subclass _run()
    # -----------------------------------------------------------------------

    def _buffer_rows(self, rows: list) -> None:
        """Add parsed rows to buffer with overflow guard.

        Call from _run() after _parse_payload() returns a non-None list.
        Handles:
        - Overflow: drops oldest entries when exceeding MAX_BUFFER_SIZE (critical alert)
        - High watermark alerting at BUFFER_ALERT_PCT (high severity)
        - Buffer depth gauge update
        """
        self._buffer.extend(rows)
        buf_len = len(self._buffer)

        if buf_len > self._overflow_threshold:
            dropped = buf_len - self._overflow_threshold
            self._buffer = self._buffer[-self._overflow_threshold :]
            buf_len = self._overflow_threshold
            self._buffer_overflow_total.inc(dropped)
            self.logger.error(
                "buffer_overflow",
                severity="critical",
                dropped=dropped,
                max_size=self._overflow_threshold,
            )

        # One-shot high-watermark: log only on threshold crossing, not every message
        if buf_len > self._alert_threshold:
            if not self._high_watermark_triggered:
                self._high_watermark_triggered = True
                self.logger.warning(
                    "buffer_high_watermark",
                    severity="high",
                    depth=buf_len,
                    threshold=self.BUFFER_ALERT_PCT,
                )
        else:
            self._high_watermark_triggered = False

        self._buffer_depth_gauge.set(buf_len)

    def _should_flush(self) -> bool:
        """Check if buffer should be flushed based on size or time interval."""
        if not self._buffer:
            return False
        now = time.monotonic()
        return (
            len(self._buffer) >= self.BATCH_SIZE
            or (now - self._last_flush) >= self.FLUSH_INTERVAL_SECS
        )

    async def maybe_flush(self) -> None:
        """Flush buffer if size or time threshold is met. Call from _run()."""
        if self._should_flush():
            await self._do_flush()
            self._last_flush = time.monotonic()

    # -----------------------------------------------------------------------
    # Flush + commit
    # -----------------------------------------------------------------------

    async def _do_flush(self) -> None:
        """Flush buffer and commit offset on success.

        Guarantees:
        - Offset committed ONLY after _flush_batch succeeds (no data loss on crash)
        - On _flush_batch exception: buffer left intact for retry

        IMPORTANT: Subclasses MUST assign self._consumer in _setup() for offset
        commits to work. Using a different attribute name (e.g. self._kafka_consumer)
        will silently skip commits, causing lag to never decrease on restart.
        """
        if not self._buffer:
            return
        batch = self._buffer[:]
        try:
            t0 = time.monotonic()
            await self._flush_batch(batch)
            self._flush_latency.observe(time.monotonic() - t0)

            self._buffer.clear()
            self._buffer_depth_gauge.set(0)

            if self._consumer and hasattr(self._consumer, "commit"):
                t0 = time.monotonic()
                await self._consumer.commit()
                self._commit_latency.observe(time.monotonic() - t0)
        except Exception:
            self._flush_errors_total.inc()
            self.logger.exception("flush_failed", batch_size=len(batch))

    # -----------------------------------------------------------------------
    # Default consume loop — subclasses can override for custom routing
    # -----------------------------------------------------------------------

    async def _run(self) -> None:
        """Standard consume→parse→buffer→flush loop.

        Works for any writer that consumes a single topic (or pre-subscribed
        multi-topic) and follows the buffer/flush pattern. Override _run() in
        subclasses that need custom routing (e.g. feature_writer's 3-loop,
        llm_writer's multi-topic dispatch).
        """
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            if not isinstance(payload, dict):
                continue
            self._record_message_consumed()
            self._on_message_consumed(payload)

            rows = self._parse_payload(payload)
            if rows is not None:
                self._buffer_rows(rows)
            else:
                self._parse_failures_total.inc()
                await self._maybe_route_to_dlq(payload, Exception("Parse failed"))

            # Backpressure: if buffer is above alert threshold, pause briefly
            if len(self._buffer) > self._alert_threshold:
                await asyncio.sleep(0.5)

            await self.maybe_flush()

    def _on_message_consumed(self, payload: dict) -> None:
        """Hook called after each message is consumed. Override for custom counters."""

    # -----------------------------------------------------------------------
    # Teardown
    # -----------------------------------------------------------------------

    async def _teardown(self) -> None:
        """Final flush before shutdown. Override to add consumer/DB cleanup."""
        if self._buffer:
            await self._do_flush()

    # -----------------------------------------------------------------------
    # Consumer lag reporting (override of BaseAgent default)
    # -----------------------------------------------------------------------

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag as buffer depth (override of BaseAgent default).

        Writer agents accumulate unflushed records in self._buffer.
        Lag = buffer size (records waiting to be flushed to DB).
        """
        # Use cached gauge from BaseAgent if available, else create
        if not hasattr(self, "_consumer_lag_gauge"):
            self._consumer_lag_gauge = PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name)

        while not self._stop_event.is_set():
            self._consumer_lag_gauge.set(len(self._buffer))
            await asyncio.sleep(15)
