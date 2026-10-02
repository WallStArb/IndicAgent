"""Tests for the phase 189 per-item IBKR history fetch (plan 03), all against fakes.

Part 1 (task 1): the stall bound, bounded retries and reconnect around one item (CD-08).
Part 2 (task 2): fetch_item, the ported per-(symbol, timeframe) body of the historical
pipeline's loop, with every provider chunk persisted atomically with its coverage (CD-04)
and an outcome classification that never charges a correct empty answer (CD-05).

No IBKR, no database: the provider, the connection, the sink and every DB helper are fakes.
Real sleeps are a few milliseconds at most.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from scripts.infrastructure.backfill._history_fetch_item import (
    ItemOutcome,
    ItemStalled,
    ProgressClock,
    fetch_item_with_retries,
    run_with_stall_bound,
)

from scripts.infrastructure.backfill import _history_fetch_item as item_mod
from scripts.infrastructure.backfill._fetch_queue import CoverageRow, QueueConfig

# ---------------------------------------------------------------------------
# Part 1: stall bound, retries, reconnect
# ---------------------------------------------------------------------------


class FakeClock:
    """Injectable time source for ProgressClock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _config(timeout_s: float = 0.03, retries: int = 2) -> QueueConfig:
    return QueueConfig(
        max_consecutive_failures=5,
        max_staleness_days_before_preempt=3,
        priority_tf_order=("15m", "1h"),
        depth_days={"1d": 7300, "15m": 7300, "5m": 7300, "1h": 7300},
        history_request_timeout_s=timeout_s,
        history_request_retries=retries,
        run_budget_minutes=240,
        default_scopes={},
    )


class RetryProvider:
    def __init__(self) -> None:
        self.disconnects = 0

    async def disconnect(self) -> None:
        self.disconnects += 1


class RetrySink:
    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> tuple[int, int]:
        self.flushes += 1
        return (0, 0)


def _retry_ctx() -> SimpleNamespace:
    return SimpleNamespace(provider=RetryProvider(), sink=RetrySink(), settings=None)


_INSTRUMENT = SimpleNamespace(symbol="AAA")
_ROW = CoverageRow("AAA", "15m", None, None, None, 0, None)


def _reconnects(*results: bool):
    calls: list[bool] = []
    queue = list(results)

    async def reconnect() -> bool:
        result = queue.pop(0) if queue else True
        calls.append(result)
        return result

    reconnect.calls = calls  # type: ignore[attr-defined]
    return reconnect


def _scripted_items(monkeypatch, script: list[str]) -> list[int]:
    """Patch fetch_item: each attempt follows the next script entry ('stall', 'ok', 'raise')."""
    attempts: list[int] = []

    async def fake_fetch_item(ctx, instrument, row, *, gap_days, full_scan, clock):
        attempts.append(len(attempts) + 1)
        step = script[len(attempts) - 1]
        if step == "stall":
            await asyncio.Event().wait()  # never set: silent socket death
        if step == "raise":
            raise RuntimeError("boom from the provider")
        return ItemOutcome(row.symbol, row.timeframe, "ok", n_bars=7)

    monkeypatch.setattr(item_mod, "fetch_item", fake_fetch_item)
    return attempts


def test_progress_clock_touch_resets_age():
    fake = FakeClock()
    clock = ProgressClock(now=fake)
    fake.now += 5.0
    assert clock.age() == pytest.approx(5.0)
    clock.touch()
    assert clock.age() == pytest.approx(0.0)
    fake.now += 1.5
    assert clock.age() == pytest.approx(1.5)


def test_progress_clock_defaults_to_monotonic():
    clock = ProgressClock()
    assert 0.0 <= clock.age() < 1.0


def test_stall_bound_returns_result_and_ticks_while_waiting():
    ticks: list[float] = []
    fake = FakeClock()  # never advances: age stays 0, so no stall however long it runs
    clock = ProgressClock(now=fake)

    async def item() -> str:
        await asyncio.sleep(0.05)
        return "done"

    result = asyncio.run(
        run_with_stall_bound(
            item, stall_timeout_s=0.03, clock=clock, on_tick=lambda: ticks.append(1.0)
        )
    )
    assert result == "done"
    # Checks every stall_timeout_s / 3 = 10 ms over a 50 ms item.
    assert len(ticks) >= 2


def test_stalled_item_is_cancelled_and_raises():
    cancelled: list[bool] = []

    async def item() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    started = time.monotonic()
    with pytest.raises(ItemStalled) as raised:
        asyncio.run(run_with_stall_bound(item, stall_timeout_s=0.03, clock=ProgressClock()))
    assert cancelled == [True]
    assert raised.value.elapsed_s >= 0.03
    assert time.monotonic() - started < 1.0


def test_stall_age_comes_from_the_clock_not_wall_time():
    fake = FakeClock()
    clock = ProgressClock(now=fake)

    def tick() -> None:
        fake.now += 10.0  # the injected clock jumps past the bound on the first check

    async def item() -> None:
        await asyncio.Event().wait()

    with pytest.raises(ItemStalled) as raised:
        asyncio.run(run_with_stall_bound(item, stall_timeout_s=0.03, clock=clock, on_tick=tick))
    assert raised.value.elapsed_s == pytest.approx(10.0)


def test_progressing_item_is_never_cancelled():
    """Touched every 5 ms, the item runs ten times the stall bound and still finishes."""
    clock = ProgressClock()

    async def item() -> int:
        for _ in range(60):
            await asyncio.sleep(0.005)
            clock.touch()
        return 60

    started = time.monotonic()
    assert asyncio.run(run_with_stall_bound(item, stall_timeout_s=0.03, clock=clock)) == 60
    assert time.monotonic() - started > 0.03 * 5


def test_retries_exhausted_is_an_error_charged_to_the_item(monkeypatch):
    attempts = _scripted_items(monkeypatch, ["stall", "stall", "stall"])
    ctx = _retry_ctx()
    reconnect = _reconnects(True, True, True)
    outcome = asyncio.run(
        fetch_item_with_retries(
            ctx,
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(retries=2),
            reconnect=reconnect,
        )
    )
    assert attempts == [1, 2, 3]
    assert outcome.status == "error"
    assert outcome.attempts == 3
    assert outcome.gateway_lost is False
    assert "stall" in (outcome.error or "")
    # Every stall disconnects and reconnects, so the next item starts on a fresh client.
    assert ctx.provider.disconnects == 3
    assert reconnect.calls == [True, True, True]


def test_reconnect_failure_is_gateway_lost(monkeypatch):
    attempts = _scripted_items(monkeypatch, ["stall", "ok"])
    ctx = _retry_ctx()
    outcome = asyncio.run(
        fetch_item_with_retries(
            ctx,
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(retries=2),
            reconnect=_reconnects(False),
        )
    )
    assert attempts == [1]
    assert outcome.status == "error"
    assert outcome.gateway_lost is True
    assert outcome.attempts == 1


def test_success_on_retry_returns_the_retry_outcome(monkeypatch):
    attempts = _scripted_items(monkeypatch, ["stall", "ok"])
    ctx = _retry_ctx()
    outcome = asyncio.run(
        fetch_item_with_retries(
            ctx,
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(retries=2),
            reconnect=_reconnects(True),
        )
    )
    assert attempts == [1, 2]
    assert outcome.status == "ok"
    assert outcome.n_bars == 7
    assert outcome.attempts == 2
    assert outcome.gateway_lost is False
    assert outcome.elapsed_s > 0


def test_stall_flushes_the_cancelled_attempts_answers_before_retrying(monkeypatch):
    _scripted_items(monkeypatch, ["stall", "ok"])
    ctx = _retry_ctx()
    asyncio.run(
        fetch_item_with_retries(
            ctx,
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(retries=1),
            reconnect=_reconnects(True),
        )
    )
    assert ctx.sink.flushes == 1


def test_other_exceptions_become_an_error_outcome_not_a_crash(monkeypatch):
    attempts = _scripted_items(monkeypatch, ["raise", "ok"])
    ctx = _retry_ctx()
    outcome = asyncio.run(
        fetch_item_with_retries(
            ctx,
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(retries=2),
            reconnect=_reconnects(),
        )
    )
    assert attempts == [1]  # not a stall: no retry
    assert outcome.status == "error"
    assert outcome.gateway_lost is False
    assert "boom from the provider" in (outcome.error or "")


def test_gateway_lost_raised_inside_the_item_is_not_charged(monkeypatch):
    async def fake_fetch_item(ctx, instrument, row, *, gap_days, full_scan, clock):
        raise item_mod.GatewayLost("reconnect before qualify failed")

    monkeypatch.setattr(item_mod, "fetch_item", fake_fetch_item)
    outcome = asyncio.run(
        fetch_item_with_retries(
            _retry_ctx(),
            _INSTRUMENT,
            _ROW,
            gap_days=0,
            full_scan=False,
            config=_config(),
            reconnect=_reconnects(),
        )
    )
    assert outcome.status == "error"
    assert outcome.gateway_lost is True
