"""OutputQueue — async output buffer extracted from IntelligencePipelineComputeAgent.

Owns the asyncio.Queue, drain loop, enqueue (non-blocking), enqueue_blocking, and join.
OTel metrics for drops, depth, and publish failures are owned here (D-16).

Usage::

    queue = OutputQueue(producer=kafka_producer, maxsize=500)
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
        producer: KafkaProducerClient used for publishing.
        maxsize:  Maximum queue depth before non-blocking enqueue drops messages.

    Note:
        ``drain_loop`` accepts a ``running_fn`` callable.  Always wire it as
        ``running_fn=lambda: self.running`` (using BaseAgent's canonical
        ``running`` property).  Passing ``self._running`` directly is wrong —
        BaseAgent does not guarantee that attribute exists.
    """

    def __init__(self, producer: KafkaProducerClient, maxsize: int) -> None:
        self._producer = producer
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
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
    # Background drain loop
    # ------------------------------------------------------------------

    async def drain_loop(self, running_fn: Callable[[], bool]) -> None:
        """Background drain loop — publish items to Kafka until agent stops.

        Args:
            running_fn: Zero-argument callable returning ``True`` while the agent
                is running.  Wire as ``lambda: self.running`` (BaseAgent canonical
                property).  Do NOT pass ``lambda: self._running``.

        The loop drains remaining items after ``running_fn()`` returns ``False``
        to preserve at-least-once delivery on graceful shutdown.

        ``task_done()`` is always called in the ``finally`` block whenever an item
        was successfully dequeued, ensuring queue accounting is never corrupted even
        if publish raises.
        """
        while running_fn() or not self._queue.empty():
            try:
                topic, key, value = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                self._buffer_depth.add(self._queue.qsize())
                await self._producer.publish(topic, msg=value, key=key)
            except Exception:
                self._publish_failures.add(1)
                self._logger.exception("output.publish_failed")
            finally:
                self._queue.task_done()
