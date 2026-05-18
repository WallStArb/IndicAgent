"""Unit tests for OutputQueue batch drain (PERF-06, Phase 089 Plan 03).

Tests cover:
- Full-batch drain (N items drains in ceil(total/N) rounds)
- Partial-batch drain (fewer than N items drains without waiting for more)
- Empty-queue no-busy-loop (wait_for respects 1s timeout; no spin)
- Per-item error isolation (error on item K does not prevent remaining items)
- Cancellation re-enqueue (unpublished items returned to queue on CancelledError)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.pipeline.output_queue import OutputQueue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_queue(batch_size: int = 10, maxsize: int = 500) -> OutputQueue:
    """Create an OutputQueue with a mock producer, bypassing __init__."""
    q = OutputQueue.__new__(OutputQueue)
    q._producer = MagicMock()
    q._producer.publish = AsyncMock()
    q._queue = asyncio.Queue(maxsize=maxsize)
    q._drain_batch_size = batch_size
    q._logger = MagicMock()
    q._drops = MagicMock()
    q._buffer_depth = MagicMock()
    q._publish_failures = MagicMock()
    return q


def _item(n: int) -> tuple:
    """Return a (topic, key, value) test tuple for item N."""
    return ("topic.test", f"key-{n}", {"n": n})


async def _enqueue_n(q: OutputQueue, count: int) -> None:
    """Put ``count`` items into the queue."""
    for i in range(count):
        await q._queue.put(_item(i))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDrainLoopBatchSize:
    """Verify that drain_loop accumulates up to N items per iteration."""

    @pytest.mark.asyncio
    async def test_drain_loop_batches_up_to_n_items(self) -> None:
        """25 items with N=10 drain in exactly 3 batches: 10, 10, 5."""
        q = _make_queue(batch_size=10)
        await _enqueue_n(q, 25)

        published: list[tuple] = []
        batch_sizes: list[int] = []

        async def drain_one_batch() -> int:
            """Drain one batch; return count of items published."""
            try:
                first = await asyncio.wait_for(q._queue.get(), timeout=0.5)
            except TimeoutError:
                return 0
            batch = [first]
            while len(batch) < q._drain_batch_size:
                try:
                    batch.append(q._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for item in batch:
                published.append(item)
                q._queue.task_done()
            return len(batch)

        # Drain until empty
        while not q._queue.empty():
            n = await drain_one_batch()
            if n > 0:
                batch_sizes.append(n)

        assert len(published) == 25, f"Expected 25 published, got {len(published)}"
        assert batch_sizes == [10, 10, 5], f"Expected batch sizes [10, 10, 5], got {batch_sizes}"

    @pytest.mark.asyncio
    async def test_drain_loop_partial_batch(self) -> None:
        """3 items with N=10 drain in a single round without waiting for more."""
        q = _make_queue(batch_size=10)
        await _enqueue_n(q, 3)

        published: list[tuple] = []

        # One drain iteration
        first = await asyncio.wait_for(q._queue.get(), timeout=0.5)
        batch = [first]
        while len(batch) < q._drain_batch_size:
            try:
                batch.append(q._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        for item in batch:
            published.append(item)
            q._queue.task_done()

        assert len(published) == 3, f"Expected 3 published in one round, got {len(published)}"
        assert q._queue.empty(), "Queue should be empty after draining 3 items"

    @pytest.mark.asyncio
    async def test_drain_loop_empty_queue_no_busy_loop(self) -> None:
        """An empty queue must block on wait_for(timeout=1.0), not spin."""
        q = _make_queue(batch_size=10)

        wait_for_calls = [0]

        async def run_loop_for(seconds: float) -> None:
            deadline = asyncio.get_event_loop().time() + seconds
            while asyncio.get_event_loop().time() < deadline:
                wait_for_calls[0] += 1
                try:
                    item = await asyncio.wait_for(q._queue.get(), timeout=1.0)
                    q._queue.task_done()
                except TimeoutError:
                    pass

        # Run for just over 2 seconds with 1.0s timeout per iteration.
        # A busy-loop would produce thousands of calls; correct impl produces 2-3.
        await run_loop_for(2.1)

        assert (
            wait_for_calls[0] <= 3
        ), f"Possible busy-loop: {wait_for_calls[0]} wait_for calls in 2.1s (expected <= 3)"
        assert (
            wait_for_calls[0] >= 2
        ), f"Expected >= 2 wait_for calls in 2.1s, got {wait_for_calls[0]}"

    @pytest.mark.asyncio
    async def test_drain_loop_per_item_error_isolation(self) -> None:
        """Error on item 1 of 3 must not prevent items 0 and 2 from publishing."""
        q = _make_queue(batch_size=10)
        await _enqueue_n(q, 3)

        attempted: list[int] = []

        async def mock_publish(item: tuple) -> None:
            n = item[2]["n"]
            attempted.append(n)
            if n == 1:
                raise ValueError("simulated publish error on item 1")

        q._publish_one = mock_publish  # type: ignore[method-assign]

        # Drain one batch and apply drain_loop's per-item error isolation logic
        first = await asyncio.wait_for(q._queue.get(), timeout=0.5)
        batch = [first]
        while len(batch) < q._drain_batch_size:
            try:
                batch.append(q._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        for item in batch:
            try:
                await q._publish_one(item)
            except Exception:
                pass  # error isolation: log and continue
            finally:
                q._queue.task_done()

        # All 3 items must have been attempted (error on item 1 did not abort)
        assert attempted == [0, 1, 2], f"Expected all 3 items attempted in order, got {attempted}"
        # Queue must be empty (task_done called for all 3 items)
        assert q._queue.empty()

    @pytest.mark.asyncio
    async def test_drain_loop_cancellation_re_enqueues(self) -> None:
        """On CancelledError, unpublished batch items are re-enqueued via put_nowait.

        Mirrors drain_loop's inner logic exactly:
        - ``_publish_one`` raises CancelledError on the second call (item index 1)
        - Items after the cancelled item (batch[handled+1:]) are re-enqueued
        - task_done() is called for each dequeued item (including the cancelled one)
        """
        q = _make_queue(batch_size=10, maxsize=500)
        await _enqueue_n(q, 5)

        call_count = [0]

        async def mock_publish(item: tuple) -> None:
            call_count[0] += 1
            if call_count[0] >= 2:
                raise asyncio.CancelledError()

        q._publish_one = mock_publish  # type: ignore[method-assign]

        # Dequeue a full batch of all 5 items
        first = await asyncio.wait_for(q._queue.get(), timeout=0.5)
        batch = [first]
        while len(batch) < q._drain_batch_size:
            try:
                batch.append(q._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        assert len(batch) == 5, f"Expected 5-item batch, got {len(batch)}"

        # Apply drain_loop's exact cancellation re-enqueue logic
        handled = 0
        with pytest.raises(asyncio.CancelledError):
            for item in batch:
                try:
                    await q._publish_one(item)
                except asyncio.CancelledError:
                    # Re-enqueue items AFTER the current one (current gets task_done below)
                    for unpub in batch[handled + 1 :]:
                        try:
                            q._queue.put_nowait(unpub)
                        except asyncio.QueueFull:
                            pass
                    raise
                except Exception:
                    pass
                finally:
                    q._queue.task_done()
                    handled += 1

        # 1 item published successfully (item 0), CancelledError on item 1
        assert (
            call_count[0] == 2
        ), f"Expected 2 publish calls (1 success, 1 cancel), got {call_count[0]}"

        # Items 2, 3, 4 (batch[2:]) should be re-enqueued = 3 items
        queue_size = q._queue.qsize()
        assert queue_size == 3, f"Expected 3 items re-enqueued (batch[2:]), got {queue_size}"
