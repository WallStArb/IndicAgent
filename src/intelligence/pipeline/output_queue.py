"""OutputQueue — async output buffer extracted from IntelligencePipelineComputeAgent.

Owns the asyncio.Queue, drain loop, enqueue (non-blocking), enqueue_blocking, and join.
OTel metrics for drops, depth, and publish failures are owned here (D-16).

Usage::

    queue = OutputQueue(producer=kafka_producer, maxsize=500, drain_batch_size=10)
    # In _run():
    asyncio.create_task(queue.drain_loop(running_fn=lambda: self.running))
    # ^ IMPORTANT: pass ``self.running`` (BaseAgent canonical property), NOT ``self._running``.
    # In _teardown():
    await asyncio.wait_for(queue.join(), timeout=10.0)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from src.core.kafka_utils import KafkaProducerClient
from src.observability.metrics import counter, gauge


class OutputQueue:
    """Async output buffer for Kafka publish.

    Thread-safe enqueue from sync code via ``enqueue()``.
    Blocking enqueue (Phase 086 contract: back-pressure instead of drop) via
    ``enqueue_blocking()``.
    Background drain loop publishes to Kafka via ``drain_loop()``.

    Args:
        producer:         KafkaProducerClient used for publishing.
        maxsize:          Maximum queue depth before non-blocking enqueue drops messages.
        drain_batch_size: Maximum number of items to publish per drain iteration.
                          Default 10. Source from
                          ``Settings.intelligence_output_drain_batch_size`` (PERF-06).

    Note:
        ``drain_loop`` accepts a ``running_fn`` callable.  Always wire it as
        ``running_fn=lambda: self.running`` (using BaseAgent's canonical
        ``running`` property).  Passing ``self._running`` directly is wrong —
        BaseAgent does not guarantee that attribute exists.
    """

    def __init__(
        self,
        producer: KafkaProducerClient,
        maxsize: int,
        drain_batch_size: int = 10,
    ) -> None:
        self._producer = producer
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._drain_batch_size = drain_batch_size
        self._logger = structlog.get_logger(__name__)
        # OTel metrics owned here per D-16
        self._drops = counter(
            "intelligence_pipeline_output_buffer_drops_total",
            "Output buffer drops due to queue full",
        )
        self._buffer_depth = gauge(
            "intelligence_pipeline_output_buffer_depth",
            "Current depth of async output queue",
        )
        self._publish_failures = counter(
            "intelligence_pipeline_output_publish_failures_total",
            "Output buffer publish failures",
        )

    # ------------------------------------------------------------------
    # Enqueue helpers
    # ------------------------------------------------------------------

    def enqueue(self, topic: str, key: str, value: Any) -> None:
        """Non-blocking enqueue to output buffer.  Drops silently on QueueFull."""
        try:
            self._queue.put_nowait((topic, key, value))
        except asyncio.QueueFull:
            self._drops.add(1)

    async def enqueue_blocking(self, topic: str, key: str, value: Any) -> None:
        """Blocking enqueue to output buffer.

        Backs up rather than dropping when the queue is full (Phase 086 contract).
        Logs a warning when the queue is already full so operators can tune maxsize.
        """
        if self._queue.full():
            self._drops.add(1)
            self._logger.warning("output_queue.full_blocking")
        await self._queue.put((topic, key, value))

    async def join(self) -> None:
        """Await until all enqueued items have been processed.

        Intended for teardown: ``await asyncio.wait_for(queue.join(), timeout=10.0)``.
        """
        await self._queue.join()

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

        Drains up to ``drain_batch_size`` items per iteration (PERF-06):
        - Blocks for the first item via ``asyncio.wait_for`` to avoid busy-looping.
        - Drains up to N-1 more items non-blocking via ``get_nowait()``.
        - Publishes all batch items preserving insertion order.
        - Per-item error isolation: publish failures on item N do not abort remaining
          items; the first exception is surfaced after the full batch completes.
        - Cancellation safety: on ``asyncio.CancelledError``, any unpublished batch
          items are re-enqueued via ``put_nowait`` (best-effort) before re-raising.

        Args:
            running_fn: Zero-argument callable returning ``True`` while the agent
                is running.  Wire as ``lambda: self.running`` (BaseAgent canonical
                property).  Do NOT pass ``lambda: self._running``.

        The loop drains remaining items after ``running_fn()`` returns ``False``
        to preserve at-least-once delivery on graceful shutdown.

        ``task_done()`` is called exactly once per item dequeued from the queue.
        Re-enqueued items (cancellation path) receive a new ``put_nowait`` call
        which increments ``_unfinished_tasks``; their ``task_done()`` fires when
        they are consumed in the next drain iteration.
        """
        while running_fn() or not self._queue.empty():
            # Block for the first item — preserves existing no-busy-loop guarantee
            try:
                first = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            # Accumulate up to drain_batch_size-1 more items non-blocking
            batch = [first]
            while len(batch) < self._drain_batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Update depth metric once per batch
            self._buffer_depth.add(self._queue.qsize())

            # Publish all items with per-item error isolation.
            # ``handled`` tracks items whose task_done() has been called so that
            # the CancelledError handler knows which items still need re-enqueuing.
            first_exc: Exception | None = None
            handled = 0

            try:
                for item in batch:
                    try:
                        await self._publish_one(item)
                    except Exception as exc:
                        self._publish_failures.add(1)
                        self._logger.error(
                            "output.publish_failed",
                            error=str(exc),
                            item_key=item[1] if len(item) > 1 else None,
                        )
                        if first_exc is None:
                            first_exc = exc
                    finally:
                        # Mark this item done regardless of publish outcome.
                        # This must fire before ``handled`` increments so the
                        # CancelledError handler sees the correct boundary.
                        self._queue.task_done()
                        handled += 1

            except asyncio.CancelledError:
                # ``handled`` items already have task_done() called above.
                # Re-enqueue the unhandled remainder best-effort.
                # put_nowait() increments _unfinished_tasks; task_done() will
                # fire when each re-enqueued item is consumed in the next run.
                for unpub in batch[handled:]:
                    try:
                        self._queue.put_nowait(unpub)
                    except asyncio.QueueFull:
                        self._logger.critical(
                            "output_queue.cancel_requeue_failed",
                            reason="queue_full_on_cancel",
                        )
                raise

            if first_exc is not None:
                raise first_exc
