"""The dashboard read cache (src/api/cache.py): one computation per TTL, failures never stored."""

import asyncio

import pytest

from src.api import cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _ttl(seconds: float, reads: list[int] | None = None):
    async def read() -> float:
        if reads is not None:
            reads.append(1)
        return seconds

    return read


def _counter(value="v", delay: float = 0.0):
    calls: list[int] = []

    async def compute():
        calls.append(1)
        await asyncio.sleep(delay)
        return value

    return compute, calls


async def test_a_hit_reuses_the_value_and_reads_no_ttl():
    compute, calls = _counter()
    reads: list[int] = []
    assert await cache.cached("k", _ttl(60, reads), compute) == "v"
    assert await cache.cached("k", _ttl(60, reads), compute) == "v"
    assert len(calls) == 1 and len(reads) == 1


async def test_an_expired_value_is_recomputed():
    compute, calls = _counter()
    await cache.cached("k", _ttl(0), compute)
    await cache.cached("k", _ttl(0), compute)
    assert len(calls) == 2


async def test_concurrent_misses_compute_once():
    compute, calls = _counter(delay=0.01)
    results = await asyncio.gather(*(cache.cached("k", _ttl(60), compute) for _ in range(10)))
    assert results == ["v"] * 10 and len(calls) == 1


async def test_keys_are_isolated():
    a, _ = _counter("a")
    b, _ = _counter("b")
    assert await cache.cached("a", _ttl(60), a) == "a"
    assert await cache.cached("b", _ttl(60), b) == "b"


async def test_a_raising_compute_stores_nothing():
    async def boom():
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await cache.cached("k", _ttl(60), boom)
    compute, calls = _counter()
    assert await cache.cached("k", _ttl(60), compute) == "v" and len(calls) == 1


async def test_a_rejected_result_is_returned_but_not_stored():
    compute, calls = _counter("partial")
    for _ in range(2):
        assert await cache.cached("k", _ttl(60), compute, keep=lambda _v: False) == "partial"
    assert len(calls) == 2


async def test_expired_slots_are_evicted_with_their_locks():
    for symbol in ("AAPL", "MSFT"):
        compute, _ = _counter()
        await cache.cached(f"universe:{symbol}", _ttl(0), compute)
    assert cache._slots == {}


async def test_requests_queued_behind_a_rejected_result_share_it():
    compute, calls = _counter("partial", delay=0.01)
    results = await asyncio.gather(
        *(cache.cached("k", _ttl(60), compute, keep=lambda _v: False) for _ in range(5))
    )
    assert results == ["partial"] * 5 and len(calls) == 1


async def test_requests_queued_behind_a_raise_share_the_error():
    calls: list[int] = []

    async def boom():
        calls.append(1)
        await asyncio.sleep(0.01)
        raise RuntimeError("db down")

    results = await asyncio.gather(
        *(cache.cached("k", _ttl(60), boom) for _ in range(5)), return_exceptions=True
    )
    assert all(isinstance(r, RuntimeError) for r in results) and len(calls) == 1


async def test_a_failed_ttl_read_runs_no_computation():
    async def bad_ttl() -> float:
        raise RuntimeError("config down")

    compute, calls = _counter()
    with pytest.raises(RuntimeError):
        await cache.cached("k", bad_ttl, compute)
    assert calls == []
