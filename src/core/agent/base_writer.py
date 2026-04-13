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
import time
from typing import Any

from prometheus_client import Counter as _Counter
from prometheus_client import Gauge as _Gauge

from src.core.agent.base import BaseAgent

# Module-level metric caches — prevent duplicate registration across
# multiple instantiations in the same process (e.g., unit tests).
_gauges: dict[str, _Gauge] = {}
_counters: dict[str, _Counter] = {}


def _get_or_create_gauge(name: str, doc: str) -> _Gauge:
    if name not in _gauges:
        _gauges[name] = _Gauge(name, doc)
    return _gauges[name]


def _get_or_create_counter(name: str, doc: str) -> _Counter:
    if name not in _counters:
        _counters[name] = _Counter(name, doc)
    return _counters[name]


class BaseWriterAgent(BaseAgent, abc.ABC):
    """Abstract base for writer agents that consume Kafka and write to DB.

    Provides the shared buffer/flush/commit/overflow/teardown pattern.
    Subclasses own their own _run() consumption loop (using self._consumer.messages()
    or self._consumer.getmany()), and call self._buffer_rows() and self._maybe_flush()
    to leverage the base class buffer management.

    Lifecycle:
        _run() → consume loop calling _buffer_rows() / _maybe_flush()
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

    # -----------------------------------------------------------------------
    # Buffer management — called from subclass _run()
    # -----------------------------------------------------------------------

    def _buffer_rows(self, rows: list) -> None:
        """Add parsed rows to buffer with overflow guard.

        Call from _run() after _parse_payload() returns a non-None list.
        Handles:
        - Overflow: drops oldest entries when exceeding MAX_BUFFER_SIZE
        - High watermark alerting at BUFFER_ALERT_PCT
        - Buffer depth gauge update
        """
        self._buffer.extend(rows)

        if len(self._buffer) > self.MAX_BUFFER_SIZE:
            dropped = len(self._buffer) - self.MAX_BUFFER_SIZE
            self._buffer = self._buffer[-self.MAX_BUFFER_SIZE :]
            self._buffer_overflow_total.inc(dropped)
            self.logger.warning("buffer_overflow", dropped=dropped, max_size=self.MAX_BUFFER_SIZE)

        # Alert on high watermark
        if len(self._buffer) > self.BUFFER_ALERT_PCT * self.MAX_BUFFER_SIZE:
            self.logger.warning(
                "buffer_high_watermark",
                depth=len(self._buffer),
                threshold=self.BUFFER_ALERT_PCT,
            )

        self._buffer_depth_gauge.set(len(self._buffer))

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
            await self._flush_batch(batch)
            self._buffer.clear()
            self._buffer_depth_gauge.set(0)
            if self._consumer and hasattr(self._consumer, "commit"):
                await self._consumer.commit()
        except Exception:
            self.logger.exception("flush_failed", batch_size=len(batch))

    # -----------------------------------------------------------------------
    # Teardown
    # -----------------------------------------------------------------------

    async def _teardown(self) -> None:
        """Final flush before shutdown. Override to add consumer/DB cleanup."""
        if self._buffer:
            await self._do_flush()
