"""OutputQueue — async output buffer extracted from IntelligencePipeline.

Owns the asyncio.Queue, drain loop, enqueue (non-blocking), enqueue_blocking, and join.
OTel metrics for drops, depth, and publish failures are owned here (D-16).

Two-queue weighted-fair drain (Phase 112 task 4-3):
- HIGH priority: intelligence, i7_signals, dlq, aggregated/winner messages
- LOW priority:  journal messages (high volume; must not starve signals)
- Drain ratio:   OUTPUT_QUEUE_DRAIN_RATIO high-priority items per 1 low-priority item
                 (default 5; configurable via settings)
- Journal drop:  if low-queue enqueue_blocking times out, increment
                 intelligence_pipeline_journal_drop_total and drop the item silently
                 (journal backpressure must NEVER stall the pipeline)

Usage::

    queue = OutputQueue(producer=kafka_producer, maxsize=500, drain_batch_size=10, drain_ratio=5)
    # In _run():
    asyncio.create_task(queue.drain_loop(running_fn=lambda: self.running))
    # ^ IMPORTANT: pass ``self.running`` (BaseDaemon canonical property), NOT ``self._running``.
    # In _teardown():
    await asyncio.wait_for(queue.join(), timeout=10.0)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from src.core.kafka_utils import KafkaProducerClient
from src.observability.metrics import counter, point_gauge

# Priority constants
PRIORITY_HIGH = "high"
PRIORITY_LOW = "low"


class OutputQueue:
    """Async output buffer for Kafka publish — two-queue weighted-fair drain.

    HIGH priority queue: intelligence, i7_signals, dlq, aggregated/winner.
    LOW priority queue:  journal (high-volume; cannot starve high-priority).

    Thread-safe enqueue from sync code via ``enqueue()``.
    Blocking enqueue (Phase 086 contract: back-pressure instead of drop) via
    ``enqueue_blocking()``.
    Background drain loop publishes to Kafka via ``drain_loop()``.

    Args:
        producer:         KafkaProducerClient used for publishing.
        maxsize:          Maximum queue depth before non-blocking enqueue drops messages.
                          Applied to both high and low queues.
        drain_batch_size: Maximum number of items to publish per drain iteration.
                          Default 10. Source from
                          ``Settings.intelligence_output_drain_batch_size`` (PERF-06).
        drain_ratio:      Weighted-fair drain: drain up to this many HIGH items per 1
                          LOW item. When HIGH is empty, LOW is drained freely.
                          Default 5. Source from ``Settings.output_queue_drain_ratio``.

    Note:
        ``drain_loop`` accepts a ``running_fn`` callable.  Always wire it as
        ``running_fn=lambda: self.running`` (using BaseDaemon's canonical
        ``running`` property).  Passing ``self._running`` directly is wrong —
        BaseDaemon does not guarantee that attribute exists.
    """

    def __init__(
        self,
        producer: KafkaProducerClient,
        maxsize: int,
        drain_batch_size: int = 10,
        drain_ratio: int = 5,
    ) -> None:
        self._producer = producer
        self._high_queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._low_queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._drain_batch_size = drain_batch_size
        self._drain_ratio = drain_ratio
        self._logger = structlog.get_logger(__name__)
        # OTel metrics owned here per D-16
        self._drops = counter(
            "intelligence_pipeline_output_buffer_drops_total",
            "Output buffer drops due to queue full",
        )
        self._buffer_depth = point_gauge(
            "intelligence_pipeline_output_buffer_depth",
            "Current depth of async output queue (max of high/low)",
        )
        self._publish_failures = counter(
            "intelligence_pipeline_output_publish_failures_total",
            "Output buffer publish failures",
        )
        self._journal_drops = counter(
            "intelligence_pipeline_journal_drop_total",
            "Journal (low-priority) items dropped due to enqueue timeout",
        )

    def _queue_for(self, priority: str) -> asyncio.Queue:
        """Return the queue for the given priority (high or low)."""
        if priority == PRIORITY_LOW:
            return self._low_queue
        return self._high_queue

    # ------------------------------------------------------------------
    # Enqueue helpers
    # ------------------------------------------------------------------

    def enqueue(self, topic: str, key: str, value: Any, *, priority: str = PRIORITY_HIGH) -> None:
        """Non-blocking enqueue to output buffer.  Drops silently on QueueFull."""
        q = self._queue_for(priority)
        try:
            q.put_nowait((topic, key, value))
        except asyncio.QueueFull:
            self._drops.add(1, {"reason": "queue_full", "priority": priority})

    async def enqueue_blocking(
        self,
        topic: str,
        key: str,
        value: Any,
        *,
        timeout_sec: float | None = None,
        priority: str = PRIORITY_HIGH,
    ) -> None:
        """Blocking enqueue to output buffer.

        For HIGH priority: backs up rather than dropping (Phase 086 contract).
        For LOW priority (journal): on timeout, increments the journal-drop counter
        and silently drops — journal backpressure must NEVER stall the pipeline.

        Logs a warning when the queue is already full so operators can tune maxsize.

        Args:
            topic:       Kafka topic name.
            key:         Kafka message key.
            value:       Message payload.
            timeout_sec: Maximum seconds to wait when the queue is full. If the
                         timeout elapses, raises ``asyncio.TimeoutError`` for HIGH
                         priority callers. For LOW priority (journal), silently drops
                         instead of raising.
                         None (default) means wait without a deadline — use only in
                         contexts that are guaranteed to be cancelled before shutdown.
            priority:    PRIORITY_HIGH (default) or PRIORITY_LOW (journal).
        """
        q = self._queue_for(priority)
        if q.full():
            self._logger.warning("output_queue.full_blocking", priority=priority)
        if timeout_sec is not None:
            try:
                await asyncio.wait_for(q.put((topic, key, value)), timeout=timeout_sec)
            except TimeoutError:
                if priority == PRIORITY_LOW:
                    # Journal drop: silently discard and increment counter (never stall pipeline)
                    self._journal_drops.add(1, {})
                    return
                # High priority: still increment drops but re-raise for caller handling
                self._drops.add(1, {"reason": "enqueue_timeout", "priority": priority})
                raise
        else:
            await q.put((topic, key, value))

    async def enqueue_many(
        self,
        items: list[tuple],
        *,
        timeout_sec: float | None = None,
    ) -> None:
        """Enqueue multiple (topic, key, value, priority) tuples in one call.

        Replaces sequential ``enqueue_blocking`` calls in _process_bar_compute —
        all non-None bar outputs (intel, i7_signals/dlq, winner, journal) are batched
        into one call to reduce per-item overhead (3-C).

        Each item is a 4-tuple: (topic, key, value, priority). Use PRIORITY_HIGH for
        intelligence/i7_signals/dlq/winner and PRIORITY_LOW for journal.

        None items are silently skipped so callers can include conditional payloads
        (e.g. winner may be absent for bars with no signals) without filtering upfront.

        On HIGH enqueue timeout: re-raises ``asyncio.TimeoutError`` (same as enqueue_blocking).
        On LOW enqueue timeout: silently drops and increments journal_drop counter.

        Args:
            items: List of (topic, key, value, priority) tuples.
            timeout_sec: Per-item enqueue timeout in seconds. Passed to each
                         enqueue_blocking call. None = wait indefinitely per item.
        """
        for item in items:
            if item is None:
                continue
            topic, key, value, priority = item
            if value is None:
                continue
            await self.enqueue_blocking(
                topic, key, value, timeout_sec=timeout_sec, priority=priority
            )

    async def join(self) -> None:
        """Await until all enqueued items in BOTH queues have been processed.

        Intended for teardown: ``await asyncio.wait_for(queue.join(), timeout=10.0)``.
        """
        await self._high_queue.join()
        await self._low_queue.join()

    # ------------------------------------------------------------------
    # Internal publish helper
    # ------------------------------------------------------------------

    async def _publish_one(self, item: tuple) -> None:
        """Publish a single (topic, key, value) tuple to Kafka."""
        topic, key, value = item
        await self._producer.publish(topic, msg=value, key=key)

    # ------------------------------------------------------------------
    # Background drain loop
    # ------------------------------------------------------------------

    async def drain_loop(self, running_fn: Callable[[], bool]) -> None:
        """Background drain loop — publish items to Kafka until agent stops.

        Weighted-fair drain: for every ``drain_ratio`` HIGH-priority items drained,
        up to 1 LOW-priority item is drained. When HIGH is empty, LOW is drained freely.

        Per drain iteration:
        - Blocks for the first item via ``asyncio.wait_for`` (HIGH preferred; falls back to LOW).
        - Drains up to drain_batch_size items total, respecting the weighted ratio.
        - Per-item error isolation: publish failure on item N does not abort remaining items.
        - Cancellation safety: unpublished batch items are re-enqueued best-effort.
        - ``task_done()`` is called on the correct queue for each item.

        Args:
            running_fn: Zero-argument callable returning ``True`` while the agent
                is running.  Wire as ``lambda: self.running`` (BaseDaemon canonical
                property).  Do NOT pass ``lambda: self._running``.

        The loop drains remaining items after ``running_fn()`` returns ``False``
        to preserve at-least-once delivery on graceful shutdown.
        """
        # Track how many HIGH items have been drained since the last LOW item
        high_drained_since_low = 0

        while running_fn() or not self._high_queue.empty() or not self._low_queue.empty():
            # Try to get the first item: prefer HIGH queue, fall back to LOW
            first_item: tuple | None = None
            first_priority: str | None = None

            # Attempt HIGH first (non-blocking)
            try:
                first_item = self._high_queue.get_nowait()
                first_priority = PRIORITY_HIGH
                high_drained_since_low += 1
            except asyncio.QueueEmpty:
                pass

            # If HIGH was empty, try LOW
            if first_item is None:
                try:
                    first_item = self._low_queue.get_nowait()
                    first_priority = PRIORITY_LOW
                    high_drained_since_low = 0
                except asyncio.QueueEmpty:
                    pass

            # If both were empty, block on HIGH with timeout, then try LOW
            if first_item is None:
                try:
                    first_item = await asyncio.wait_for(self._high_queue.get(), timeout=1.0)
                    first_priority = PRIORITY_HIGH
                    high_drained_since_low += 1
                except TimeoutError:
                    # HIGH timed out — try LOW before looping
                    try:
                        first_item = self._low_queue.get_nowait()
                        first_priority = PRIORITY_LOW
                        high_drained_since_low = 0
                    except asyncio.QueueEmpty:
                        continue

            if first_item is None:
                continue

            # Build batch starting with the first item
            # batch entries are (item, priority) tuples for correct task_done routing
            batch: list[tuple[tuple, str]] = [(first_item, first_priority)]

            while len(batch) < self._drain_batch_size:
                # Determine which queue to drain next based on weighted ratio
                can_drain_high = not self._high_queue.empty()
                can_drain_low = (
                    not self._low_queue.empty() and high_drained_since_low >= self._drain_ratio
                )

                if can_drain_high:
                    try:
                        item = self._high_queue.get_nowait()
                        batch.append((item, PRIORITY_HIGH))
                        high_drained_since_low += 1
                    except asyncio.QueueEmpty:
                        pass
                elif can_drain_low:
                    try:
                        item = self._low_queue.get_nowait()
                        batch.append((item, PRIORITY_LOW))
                        high_drained_since_low = 0
                    except asyncio.QueueEmpty:
                        break
                else:
                    break

            # Update depth metric once per batch (max of both queues)
            self._buffer_depth.set(max(self._high_queue.qsize(), self._low_queue.qsize()))

            # Publish all items with per-item error isolation.
            handled = 0

            try:
                for item, priority in batch:
                    q = self._queue_for(priority)
                    try:
                        await self._publish_one(item)
                    except Exception as exc:
                        self._publish_failures.add(1)
                        self._logger.error(
                            "output.publish_failed",
                            error=str(exc),
                            item_key=item[1] if len(item) > 1 else None,
                            priority=priority,
                        )
                    finally:
                        # Mark this item done on the correct queue.
                        q.task_done()
                        handled += 1

            except asyncio.CancelledError:
                # Re-enqueue unhandled items best-effort (preserving priority)
                for unpub_item, unpub_priority in batch[handled:]:
                    q = self._queue_for(unpub_priority)
                    try:
                        q.put_nowait(unpub_item)
                    except asyncio.QueueFull:
                        self._logger.critical(
                            "output_queue.cancel_requeue_failed",
                            reason="queue_full_on_cancel",
                            priority=unpub_priority,
                        )
                raise

            # Intentionally do NOT re-raise first_exc here.
            # The _publish_failures counter and error log above provide observability.
            # Re-raising would terminate the drain loop on the first publish failure,
            # silently dropping all remaining queued items.
