"""Unit tests for PerKeyWorkerManager — concurrency, ordering, filtering, back-pressure, shutdown."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.pipeline.per_key_worker_manager import PerKeyWorkerManager


def _make_bar(symbol: str, tf: str = "1m") -> MagicMock:
    bar = MagicMock()
    bar.symbol = symbol
    bar.tf = tf
    return bar


@pytest.mark.asyncio
async def test_independent_keys_run_concurrently() -> None:
    """Bars for different (symbol, tf) keys are processed concurrently."""
    order: list[str] = []
    barrier = asyncio.Event()

    async def slow_es(bar):  # noqa: ANN001
        await barrier.wait()
        order.append("ES")

    async def fast_nq(bar):  # noqa: ANN001
        order.append("NQ")

    results: dict[str, asyncio.Task] = {}

    async def processor(bar):  # noqa: ANN001
        if bar.symbol == "ES":
            await slow_es(bar)
        else:
            await fast_nq(bar)

    mgr = PerKeyWorkerManager(processor=processor)
    await mgr.enqueue(_make_bar("ES"))
    await mgr.enqueue(_make_bar("NQ"))

    # Give NQ worker time to complete before releasing ES
    await asyncio.sleep(0.05)
    barrier.set()
    await asyncio.sleep(0.05)

    assert order[0] == "NQ", "NQ should complete before ES (concurrent execution)"
    await mgr.stop()


@pytest.mark.asyncio
async def test_within_key_order_preserved() -> None:
    """Bars for the same key are processed in FIFO arrival order."""
    processed: list[int] = []

    async def processor(bar):  # noqa: ANN001
        processed.append(bar.seq)

    mgr = PerKeyWorkerManager(processor=processor)
    for i in range(5):
        b = _make_bar("ES")
        b.seq = i
        await mgr.enqueue(b)

    await asyncio.sleep(0.1)
    await mgr.stop()
    assert processed == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_symbol_filter_drops_unowned() -> None:
    """Bars for symbols not in the filter are silently dropped."""
    calls: list[str] = []

    async def processor(bar):  # noqa: ANN001
        calls.append(bar.symbol)

    mgr = PerKeyWorkerManager(processor=processor, symbol_filter=frozenset({"ES"}))
    await mgr.enqueue(_make_bar("NQ"))  # should be dropped
    await mgr.enqueue(_make_bar("ES"))  # should be processed

    await asyncio.sleep(0.1)
    await mgr.stop()
    assert calls == ["ES"]
    assert "NQ" not in calls


@pytest.mark.asyncio
async def test_back_pressure_blocks_producer() -> None:
    """enqueue() blocks when the per-key queue is full (maxsize=1)."""
    processing = asyncio.Event()
    release = asyncio.Event()

    async def slow_processor(bar):  # noqa: ANN001
        processing.set()
        await release.wait()

    mgr = PerKeyWorkerManager(processor=slow_processor, queue_maxsize=1)
    await mgr.enqueue(_make_bar("ES"))  # worker picks this up
    await processing.wait()  # worker is now blocked
    await mgr.enqueue(_make_bar("ES"))  # fills the queue (maxsize=1)

    # Next enqueue should block since queue is full
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(mgr.enqueue(_make_bar("ES")), timeout=0.05)

    release.set()
    await mgr.stop()


@pytest.mark.asyncio
async def test_stop_cancels_all_workers() -> None:
    """stop() cancels all per-key worker tasks cleanly."""
    processor = AsyncMock()
    mgr = PerKeyWorkerManager(processor=processor)

    for symbol in ("ES", "NQ", "CL"):
        await mgr.enqueue(_make_bar(symbol))

    await asyncio.sleep(0.05)
    assert len(mgr._tasks) == 3

    await mgr.stop()
    assert all(t.done() for t in mgr._tasks.values())
