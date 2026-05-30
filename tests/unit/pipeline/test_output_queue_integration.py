"""Unit tests for OutputQueue (extracted from IntelligencePipeline).

Exercises the class in isolation using fakes — no full agent instantiation.
Tests verify: drop-on-full, blocking back-pressure, drain publishes via msg= kwarg,
task_done always called (try/finally architectural assertion), and join after drain.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock

import pytest

from src.intelligence.pipeline.output_queue import OutputQueue

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_output_queue(maxsize: int = 5) -> OutputQueue:
    """Construct OutputQueue with an AsyncMock producer."""
    producer = AsyncMock()
    producer.publish = AsyncMock()
    return OutputQueue(producer=producer, maxsize=maxsize)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_non_blocking_drops_on_full() -> None:
    """enqueue() must silently drop when queue is at maxsize, not raise."""
    q = make_output_queue(maxsize=3)
    # Fill queue to capacity
    for i in range(3):
        q.enqueue("topic", "key", {"i": i})
    assert q._queue.qsize() == 3
    # This must not raise
    q.enqueue("topic", "key", {"overflow": True})
    # Queue size must still be maxsize (overflow item dropped)
    assert q._queue.qsize() == 3


@pytest.mark.asyncio
async def test_enqueue_blocking_awaits_on_full() -> None:
    """enqueue_blocking() must block (not drop) when queue is full."""
    q = make_output_queue(maxsize=1)
    # Fill queue
    q.enqueue("topic", "key", {"first": True})
    assert q._queue.full()

    # Start a blocking enqueue in a background task
    enqueue_task = asyncio.create_task(q.enqueue_blocking("topic", "key", {"second": True}))

    # Give the event loop a chance to run — task should be stuck waiting
    await asyncio.sleep(0)
    assert not enqueue_task.done(), "enqueue_blocking should not complete while queue is full"

    # Drain the queue to unblock the blocked enqueue
    item = await asyncio.wait_for(q._queue.get(), timeout=1.0)
    q._queue.task_done()
    assert item[2] == {"first": True}

    # Now the blocking enqueue should complete
    await asyncio.wait_for(enqueue_task, timeout=1.0)
    assert enqueue_task.done()
    assert q._queue.qsize() == 1


@pytest.mark.asyncio
async def test_drain_loop_publishes_via_producer_msg_kwarg() -> None:
    """drain_loop must call producer.publish with msg= kwarg (CLAUDE.md contract)."""
    q = make_output_queue()
    q.enqueue("test.topic", "test-key", {"data": "value"})

    # Run the drain loop for a brief window: returns True once, then False
    call_count = 0

    def running_fn() -> bool:
        nonlocal call_count
        call_count += 1
        # True on first call so loop runs; False after queue is empty
        return not q._queue.empty()

    await asyncio.wait_for(q.drain_loop(running_fn=running_fn), timeout=2.0)

    q._producer.publish.assert_awaited_once()
    _, kwargs = q._producer.publish.call_args
    assert "msg" in kwargs, "publish must use msg= kwarg (not value=)"
    assert kwargs["msg"] == {"data": "value"}
    assert kwargs["key"] == "test-key"


@pytest.mark.asyncio
async def test_drain_loop_calls_task_done_on_publish_exception() -> None:
    """task_done() must be called even when producer.publish raises."""
    q = make_output_queue()
    q._producer.publish = AsyncMock(side_effect=RuntimeError("kafka down"))

    q.enqueue("topic", "key", {"msg": "fail"})

    # Loop runs once (True while non-empty), then stops
    def running_fn() -> bool:
        return not q._queue.empty()

    with pytest.raises(RuntimeError, match="kafka down"):
        await asyncio.wait_for(q.drain_loop(running_fn=running_fn), timeout=2.0)

    # Queue should be fully drained (task_done called before exception surfaced)
    # If task_done was NOT called, join() would hang forever
    await asyncio.wait_for(q._queue.join(), timeout=1.0)


@pytest.mark.asyncio
async def test_drain_loop_calls_task_done_in_finally_block() -> None:
    """Architectural assertion: drain_loop source must contain try/finally with task_done.

    This test exists to prevent future refactors from accidentally removing the
    finally clause and silently corrupting queue accounting.
    """
    source = inspect.getsource(OutputQueue.drain_loop)
    assert "finally:" in source, "drain_loop must have a finally: block"
    # Find the last occurrence of task_done (the actual call, not docstring mention)
    assert "task_done" in source, "drain_loop must call task_done()"
    # Strip the docstring by finding code after the first triple-quote block closes
    # Find where the body starts (after the def line and docstring)
    lines = source.splitlines()
    # Skip until we're past the docstring (find line after closing """)
    in_docstring = False
    code_start_line = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0:
            continue  # def line
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                code_start_line = i + 1
                break
            else:
                in_docstring = True
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    # Single-line docstring
                    in_docstring = False
                    code_start_line = i + 1
                    break

    code_body = "\n".join(lines[code_start_line:])
    assert "finally:" in code_body, "drain_loop code body must have a finally: block"
    finally_pos = code_body.index("finally:")
    # task_done must appear after finally: in the code body
    remaining = code_body[finally_pos:]
    assert (
        "task_done" in remaining
    ), "task_done() must appear inside (after) the finally: block in drain_loop"


@pytest.mark.asyncio
async def test_drain_loop_running_fn_signature_is_callable_bool() -> None:
    """drain_loop must accept a zero-argument callable returning bool."""
    sig = inspect.signature(OutputQueue.drain_loop)
    params = list(sig.parameters.keys())
    # self + running_fn
    assert "running_fn" in params, "drain_loop must have running_fn parameter"
    # Confirm it accepts a callable — pass a lambda and verify no TypeError
    q = make_output_queue()

    async def _run() -> None:
        await q.drain_loop(running_fn=lambda: False)

    await asyncio.wait_for(_run(), timeout=1.0)


@pytest.mark.asyncio
async def test_join_returns_when_drained() -> None:
    """join() must return promptly once all enqueued items are processed."""
    q = make_output_queue()
    q.enqueue("t", "k", {"x": 1})

    # Manually drain the item and call task_done
    item = await asyncio.wait_for(q._queue.get(), timeout=1.0)
    assert item[2] == {"x": 1}
    q._queue.task_done()

    # join() should return immediately now
    await asyncio.wait_for(q.join(), timeout=1.0)
