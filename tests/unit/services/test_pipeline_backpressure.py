"""Regression tests for intelligence pipeline backpressure — Phase 106.

Tests prove:
- Intel and journal enqueue calls use enqueue_blocking (not fire-and-forget enqueue)
- enqueue_blocking puts onto the queue (does not drop) when queue is full
- Under queue-full conditions, enqueue_blocking awaits (blocks) rather than returning immediately
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Source inspection: intel + journal use enqueue_blocking exclusively
# ---------------------------------------------------------------------------


def test_intel_and_journal_use_blocking_enqueue():
    """intelligence_pipeline_agent uses only enqueue_blocking for intel/journal output.

    Reads the agent source and asserts:
    - enqueue_blocking is present (used for intel + journal publish)
    - enqueue( is not called directly (non-blocking fire-and-forget path is not used)

    This is a structural invariant: switching to non-blocking enqueue would silently
    drop messages when the queue is full (Phase 086 back-pressure contract).
    """
    import ast
    from pathlib import Path

    source = Path("services/feature_vector_pipeline.py").read_text()

    # Must use enqueue_blocking for intel + journal
    assert (
        "enqueue_blocking" in source
    ), "intelligence_pipeline_agent must call enqueue_blocking for back-pressure"

    # Parse AST to find direct calls to self._out_queue.enqueue(
    # (as opposed to enqueue_blocking — which is fine)
    tree = ast.parse(source)

    direct_enqueue_calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "enqueue"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_out_queue"
        ):
            direct_enqueue_calls.append(node)

    assert direct_enqueue_calls == [], (
        f"Found {len(direct_enqueue_calls)} direct self._out_queue.enqueue() call(s) — "
        "intel/journal must use enqueue_blocking to avoid silent drops"
    )


# ---------------------------------------------------------------------------
# enqueue_blocking behaviour: does not drop, does await on full queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_blocking_puts_on_queue():
    """enqueue_blocking puts the item onto the HIGH queue (no drop, default priority=HIGH)."""
    from src.intelligence.pipeline.output_queue import OutputQueue

    producer = AsyncMock()
    queue = OutputQueue(producer=producer, maxsize=10, drain_batch_size=5)

    await queue.enqueue_blocking("topic.test", "key1", {"data": 1})

    assert queue._high_queue.qsize() == 1


@pytest.mark.asyncio
async def test_enqueue_blocking_awaits_on_full_queue():
    """enqueue_blocking suspends (back-pressure) rather than dropping on full queue.

    Strategy: fill the HIGH queue to maxsize, then call enqueue_blocking in a task.
    The task must NOT complete before we drain one slot — proving it awaits.
    """
    from src.intelligence.pipeline.output_queue import OutputQueue

    producer = AsyncMock()
    maxsize = 3
    queue = OutputQueue(producer=producer, maxsize=maxsize, drain_batch_size=10)

    # Fill the HIGH queue to capacity using non-blocking puts
    for i in range(maxsize):
        await queue._high_queue.put(("topic", f"k{i}", {"i": i}))

    assert queue._high_queue.full()

    # Attempt to enqueue_blocking (HIGH priority, default) — should suspend since queue is full
    task = asyncio.create_task(
        queue.enqueue_blocking("topic.test", "blocked_key", {"blocked": True})
    )

    # Yield control — if enqueue_blocking had returned immediately, task would be done
    await asyncio.sleep(0)
    assert not task.done(), "enqueue_blocking returned immediately on full queue — should block"

    # Drain one item so enqueue_blocking can proceed
    item = queue._high_queue.get_nowait()
    queue._high_queue.task_done()

    # Now the blocking enqueue should complete
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()

    # Item was enqueued (queue has maxsize items again: maxsize-1 originals + 1 new)
    assert queue._high_queue.qsize() == maxsize


@pytest.mark.asyncio
async def test_non_blocking_enqueue_drops_on_full_queue():
    """Control test: non-blocking enqueue() drops silently when queue is full.

    This contrasts with enqueue_blocking — confirms we understand both paths.
    """
    from src.intelligence.pipeline.output_queue import OutputQueue

    producer = AsyncMock()
    maxsize = 2
    queue = OutputQueue(producer=producer, maxsize=maxsize, drain_batch_size=5)

    # Fill HIGH queue (default priority)
    for i in range(maxsize):
        await queue._high_queue.put(("topic", f"k{i}", {}))

    # Non-blocking enqueue on full queue — should drop (no await)
    queue.enqueue("topic.drop", "dropped_key", {"dropped": True})

    # Queue size unchanged (dropped)
    assert queue._high_queue.qsize() == maxsize


@pytest.mark.asyncio
async def test_enqueue_blocking_drop_counter_only_on_actual_drop():
    """Drop counter must NOT fire when enqueue_blocking succeeds despite queue being full.

    The counter must fire only when asyncio.TimeoutError is raised (true data loss).
    False-positive drops were caused by incrementing the counter before the blocking
    put() completed — making the metric unreliable for alerting on actual data loss.
    """
    from src.intelligence.pipeline.output_queue import OutputQueue

    producer = AsyncMock()
    maxsize = 1
    queue = OutputQueue(producer=producer, maxsize=maxsize, drain_batch_size=5)

    # Fill the HIGH queue to capacity
    await queue._high_queue.put(("topic", "existing", {}))
    assert queue._high_queue.full()

    drop_calls: list = []
    original_add = queue._drops.add

    def track_add(n, attrs=None):
        drop_calls.append(n)
        return original_add(n, attrs) if attrs else original_add(n)

    queue._drops.add = track_add

    # Drain one slot so the blocking put can succeed
    async def drain_one():
        await asyncio.sleep(0.01)
        queue._high_queue.get_nowait()
        queue._high_queue.task_done()

    asyncio.create_task(drain_one())
    await queue.enqueue_blocking("topic", "new_key", {}, timeout_sec=1.0)

    # Message was enqueued successfully — no drop should have been counted
    assert drop_calls == [], f"Drop counter fired {len(drop_calls)} time(s) on a successful put"
