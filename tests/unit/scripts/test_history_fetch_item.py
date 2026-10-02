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
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts.infrastructure.backfill import _history_fetch_item as item_mod
from scripts.infrastructure.backfill import (
    infrastructure_run_historical_pipeline as pipeline,
)
from scripts.infrastructure.backfill._fetch_queue import CoverageRow, QueueConfig
from scripts.infrastructure.backfill._history_fetch_item import (
    FetchContext,
    ItemOutcome,
    ItemStalled,
    ProgressClock,
    fetch_item,
    fetch_item_with_retries,
    run_with_stall_bound,
)
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.core.models import AssetClass
from src.providers.base import OHLCVBar

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


# ---------------------------------------------------------------------------
# Part 2: fetch_item
# ---------------------------------------------------------------------------

_END = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
_GAP = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 15, tzinfo=UTC))
_RUN_ID = "item-test-run-id"


def _bars(symbol: str, tf: str, n: int = 4) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            symbol=symbol,
            timeframe=tf,
            timestamp=datetime(2024, 1, 2 + i, tzinfo=UTC),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000 * (i + 1),
            source="ibkr",
        )
        for i in range(n)
    ]


class FakeCursor:
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, *args, **kwargs) -> None:
        return None


class FakeConn:
    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def close(self) -> None:
        return None


class FakeSink:
    def __init__(self) -> None:
        self.requests: list[SimpleNamespace] = []
        self.observations: list[tuple[object, list]] = []
        self.total_requests = 0
        self.total_observations = 0
        self.flushes = 0
        self.fail_flush = False

    def on_request(self, record) -> None:
        self.requests.append(record)

    def on_observation(self, record, bars) -> None:
        self.observations.append((record, bars))

    def take_requests(self, request_ids) -> list:
        wanted = {str(rid) for rid in request_ids}
        taken = [rec for rec in self.requests if str(rec.request_id) in wanted]
        self.requests = [rec for rec in self.requests if str(rec.request_id) not in wanted]
        return taken

    def flush(self) -> tuple[int, int]:
        self.flushes += 1
        if self.fail_flush:
            raise RuntimeError("D1 flush failed")
        n = (len(self.requests), len(self.observations))
        self.total_requests += n[0]
        self.total_observations += n[1]
        self.requests, self.observations = [], []
        return n


class FakeProvider:
    """Records fetch kwargs; answers each fetch with a record, then its chunk (todo 462 order)."""

    def __init__(self, bars_by_tf: dict[str, list[OHLCVBar]] | None = None) -> None:
        self.calls: list[dict] = []
        self.bars_by_tf = bars_by_tf
        self.last_fetch_failed_chunks = 0
        self.failed_chunks_by_tf: dict[str, int] = {}
        self.qualify_result = True
        self.qualify_calls: list[str] = []
        self.head_calls: list[str] = []
        self.head_answer: tuple[datetime | None, str | None] = (None, "fake head lookup")
        self.connected = True
        self.connect_result = True
        self.raise_on_fetch: Exception | None = None
        self._n_records = 0

    async def connect(self) -> bool:
        self.connected = self.connect_result
        return self.connect_result

    async def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    async def qualify_instrument(self, instrument) -> bool:
        self.qualify_calls.append(instrument.symbol)
        return self.qualify_result

    async def get_head_timestamp(self, symbol: str):
        self.head_calls.append(symbol)
        return self.head_answer

    def _record(self, kwargs: dict, route: str) -> SimpleNamespace:
        self._n_records += 1
        return SimpleNamespace(
            request_id=f"{kwargs['symbol']}-{kwargs['timeframe']}-{route}-{self._n_records}",
            fetch_run_id=kwargs.get("fetch_run_id"),
            symbol=kwargs["symbol"],
            timeframe=kwargs["timeframe"],
            route=route,
        )

    async def fetch_historical_bars(self, **kwargs) -> list[OHLCVBar]:
        self.calls.append(kwargs)
        if self.raise_on_fetch is not None:
            raise self.raise_on_fetch
        tf = kwargs["timeframe"]
        bars = (
            list(self.bars_by_tf.get(tf, []))
            if self.bars_by_tf is not None
            else _bars(kwargs["symbol"], tf)
        )
        on_request = kwargs.get("on_request")
        on_observation = kwargs.get("on_observation")
        if on_request is not None:
            if tf == "1d":
                # SMART answer then a former-venue recovery: two requests, two observations.
                smart, venue = self._record(kwargs, "SMART"), self._record(kwargs, "NYSE")
                on_request(smart)
                if on_observation is not None:
                    on_observation(smart, bars[:2])
                on_request(venue)
                if on_observation is not None:
                    on_observation(venue, bars[2:])
            else:
                on_request(self._record(kwargs, "SMART"))
        if kwargs.get("on_chunk") is not None and bars:
            await kwargs["on_chunk"](bars)
        self.last_fetch_failed_chunks = self.failed_chunks_by_tf.get(tf, 0)
        return bars


class SpyClock(ProgressClock):
    def __init__(self) -> None:
        super().__init__()
        self.touches = 0

    def touch(self) -> None:
        self.touches += 1
        super().touch()


@pytest.fixture
def env(monkeypatch):
    """Patch every DB-touching helper at the _history_fetch_item module level."""
    rec = SimpleNamespace(
        persist=[],
        stored=[],
        marked=[],
        normalized=[],
        gap_calls=[],
        reconciled=[],
        heads_recorded=[],
        per_contract=[],
        gaps=[_GAP],
        synthetic=False,
        bars_1m=[],
    )

    def fake_persist(conn, *, request_rows, archive_rows, write_archive_rows, coverage=None):
        rec.persist.append(
            SimpleNamespace(
                requests=list(request_rows),
                rows=list(archive_rows),
                writer=write_archive_rows,
                coverage=coverage,
            )
        )
        return len(request_rows), len(archive_rows)

    def fake_detect_gaps(conn, symbol, tf, start, end, **kwargs):
        rec.gap_calls.append(
            SimpleNamespace(symbol=symbol, tf=tf, start=start, end=end, answered=kwargs["answered"])
        )
        return list(rec.gaps)

    def fake_normalize(bars, **kwargs):
        rec.normalized.append((kwargs["symbol"], kwargs["timeframe"]))
        out = list(bars)
        if rec.synthetic:
            out.append(
                {
                    "timestamp": datetime(2024, 1, 1, tzinfo=UTC),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 0,
                    "source": SOURCE_SYNTHETIC_FILL,
                }
            )
        return out

    def fake_store(conn, bars, symbol, tf, actual_symbol=None, write_rows=None):
        rec.stored.append(SimpleNamespace(symbol=symbol, tf=tf, bars=list(bars), writer=write_rows))
        return len(bars)

    async def fake_per_contract(**kwargs):
        rec.per_contract.append(kwargs)
        return 12, []

    monkeypatch.setattr(item_mod, "persist_chunk_atomically", fake_persist)
    monkeypatch.setattr(item_mod, "detect_gaps", fake_detect_gaps)
    monkeypatch.setattr(
        item_mod, "load_answered_windows", lambda conn, symbol, tf: ("answered", symbol, tf)
    )
    monkeypatch.setattr(item_mod, "normalize_bars", fake_normalize)
    monkeypatch.setattr(item_mod, "store_bars", fake_store)
    monkeypatch.setattr(
        item_mod,
        "mark_fetch_complete",
        lambda conn, symbol, tf, since: rec.marked.append((symbol, tf, since)),
    )
    monkeypatch.setattr(item_mod, "fetch_per_contract", fake_per_contract)
    monkeypatch.setattr(item_mod, "fetch_bars", lambda conn, symbol, tf: list(rec.bars_1m))
    monkeypatch.setattr(
        item_mod.empty_history,
        "apply_empty_range",
        lambda gaps, empty, now, reverify, interval, min_confirmations: gaps,
    )
    monkeypatch.setattr(
        item_mod.empty_history, "reconcile", lambda *a, **k: rec.reconciled.append(a)
    )
    monkeypatch.setattr(
        item_mod.empty_history, "record_head", lambda *a, **k: rec.heads_recorded.append(a)
    )
    return rec


def _ctx(provider: FakeProvider, **overrides) -> FetchContext:
    fields = dict(
        provider=provider,
        settings=None,
        connect=FakeConn,
        sink=FakeSink(),
        fetch_run_id=_RUN_ID,
        tf_fetch_config={
            "1d": (7300, True),
            "1h": (7300, False),
            "15m": (7300, True),
            "5m": (7300, True),
            "1m": (90, True),
        },
        end_dt=_END,
        run_started_at=_END,
        empty_ranges={},
        empty_reverify_days=7,
        fresh_heads={},
        first_bars={},
    )
    fields.update(overrides)
    return FetchContext(**fields)


def _instrument(symbol: str = "AAA", asset_class: AssetClass = AssetClass.EQUITY):
    return SimpleNamespace(
        symbol=symbol, asset_class=asset_class, session_id="nyse", exchange="NYSE"
    )


def _row(
    tf: str,
    symbol: str = "AAA",
    latest: datetime | None = None,
    status: str | None = None,
) -> CoverageRow:
    earliest = None if latest is None else datetime(2006, 10, 2, tzinfo=UTC)
    return CoverageRow(symbol, tf, earliest, latest, status, 0, None)


def _fetch(ctx, row, *, instrument=None, gap_days=0, full_scan=False, clock=None):
    return asyncio.run(
        fetch_item(
            ctx,
            instrument or _instrument(row.symbol),
            row,
            gap_days=gap_days,
            full_scan=full_scan,
            clock=clock or ProgressClock(),
        )
    )


# --- window selection (todo 387) -------------------------------------------

_COVERED_LATEST = datetime(2026, 9, 30, 15, 45, tzinfo=UTC)


@pytest.mark.parametrize(
    "row, gap_days, full_scan",
    [
        (_row("15m", latest=_COVERED_LATEST, status="ok"), 30, False),  # gap left
        (_row("15m", latest=_COVERED_LATEST, status="error"), 0, False),  # last fetch failed
        (_row("15m", latest=_COVERED_LATEST, status="no_data"), 0, False),
        (_row("15m", latest=_COVERED_LATEST, status="ok"), 0, True),  # operator full scan
        (_row("15m"), 0, False),  # never fetched
    ],
)
def test_full_depth_window_when_the_series_is_not_fully_covered(env, row, gap_days, full_scan):
    _fetch(_ctx(FakeProvider()), row, gap_days=gap_days, full_scan=full_scan)
    assert env.gap_calls[0].start == pipeline._fetch_start(_END, 7300)
    assert env.gap_calls[0].end == _END


def test_fully_covered_series_scans_only_from_its_latest_bar(env):
    row = _row("15m", latest=_COVERED_LATEST, status="ok")
    _fetch(_ctx(FakeProvider()), row, gap_days=0)
    assert env.gap_calls[0].start == datetime(2026, 9, 30, tzinfo=UTC)


def test_days_override_caps_the_depth(env):
    _fetch(_ctx(FakeProvider(), days_override=10), _row("15m"))
    assert env.gap_calls[0].start == pipeline._fetch_start(_END, 10)


# --- persistence routing (CD-04) -------------------------------------------


def test_15m_chunks_persist_atomically_into_the_archive_with_coverage(env):
    ctx = _ctx(FakeProvider())
    outcome = _fetch(ctx, _row("15m"))
    assert outcome.status == "ok" and outcome.n_bars == 4
    assert len(env.persist) == 1
    call = env.persist[0]
    assert call.writer is pipeline._insert_archive_rows
    assert call.coverage.destination == "archive"
    assert (call.coverage.symbol, call.coverage.timeframe) == ("AAA", "15m")
    assert len(call.requests) == 1  # the chunk's answer, taken off the sink
    assert call.requests[0].timeframe == "15m"
    assert all(len(r) == 10 and r[1] == "AAA" and r[2] == "15m" for r in call.rows)
    # 15m is real-bars-only: no fill, no post-pass store.
    assert env.stored == [] and env.normalized == []


@pytest.mark.parametrize("tf", ["5m", "1d"])
def test_grid_timeframe_chunks_persist_atomically_into_the_grid_with_coverage(env, tf):
    ctx = _ctx(FakeProvider())
    outcome = _fetch(ctx, _row(tf))
    assert outcome.status == "ok"
    assert len(env.persist) == 1
    call = env.persist[0]
    assert call.writer is pipeline._insert_market_data_rows
    assert call.coverage.destination == "grid"
    assert (call.coverage.symbol, call.coverage.timeframe) == ("AAA", tf)
    assert all(len(r) == 9 and r[2] == tf for r in call.rows)
    assert call.requests  # grid timeframes record their answers atomically too
    assert outcome.n_grid_source_rows == (4 if tf == "5m" else 0)


def test_placeholder_fill_is_stored_without_coverage(env):
    """1d keeps the placeholder path: the synthetic fill is not a provider bar, so it goes
    through store_bars and never through the coverage write."""
    env.synthetic = True
    ctx = _ctx(FakeProvider())
    _fetch(ctx, _row("1d"))
    assert len(env.persist) == 1 and len(env.persist[0].rows) == 4
    assert len(env.stored) == 1
    stored = env.stored[0]
    assert stored.writer is None  # default grid insert, outside the atomic coverage path
    assert [b["source"] for b in stored.bars] == [SOURCE_SYNTHETIC_FILL]


def test_returned_bars_missed_by_on_chunk_are_still_persisted_atomically(env):
    class NoChunkProvider(FakeProvider):
        async def fetch_historical_bars(self, **kwargs):
            kwargs = dict(kwargs, on_chunk=None)
            return await super().fetch_historical_bars(**kwargs)

    _fetch(_ctx(NoChunkProvider()), _row("15m"))
    assert len(env.persist) == 1 and len(env.persist[0].rows) == 4
    assert env.persist[0].coverage is not None


def test_clock_is_touched_by_requests_and_persisted_chunks(env):
    clock = SpyClock()
    _fetch(_ctx(FakeProvider()), _row("15m"), clock=clock)
    assert clock.touches >= 2  # one request record, one persisted chunk


# --- outcome classification (CD-05) -----------------------------------------


def test_no_gaps_is_ok_without_a_fetch(env):
    env.gaps = []
    provider = FakeProvider()
    outcome = _fetch(_ctx(provider), _row("15m"))
    assert outcome.status == "ok" and outcome.n_bars == 0
    assert provider.calls == []


def test_answered_with_zero_bars_is_no_data(env):
    provider = FakeProvider(bars_by_tf={})
    outcome = _fetch(_ctx(provider), _row("15m"))
    assert outcome.status == "no_data"
    assert outcome.error is None
    assert env.persist == []


def test_failed_chunks_are_an_error_and_skip_mark_fetch_complete(env):
    provider = FakeProvider()
    provider.failed_chunks_by_tf = {"15m": 1}
    outcome = _fetch(_ctx(provider), _row("15m"))
    assert outcome.status == "error"
    assert env.marked == []
    assert len(env.persist) == 1  # what did arrive is still committed with its coverage


def test_window_exception_is_an_error(env):
    provider = FakeProvider()
    provider.raise_on_fetch = RuntimeError("socket closed")
    outcome = _fetch(_ctx(provider), _row("15m"))
    assert outcome.status == "error"
    assert "socket closed" in (outcome.error or "")
    assert env.marked == []


def test_clean_fetch_marks_complete_from_the_window_start(env):
    _fetch(_ctx(FakeProvider()), _row("5m"))
    assert env.marked == [("AAA", "5m", pipeline._fetch_start(_END, 7300))]


# --- per-run caches -----------------------------------------------------------


def test_qualify_failure_is_an_error_and_cached_per_symbol(env):
    provider = FakeProvider()
    provider.qualify_result = False
    ctx = _ctx(provider)
    first = _fetch(ctx, _row("15m"))
    second = _fetch(ctx, _row("1h"))
    assert first.status == second.status == "error"
    assert "qualify" in (first.error or "")
    assert provider.qualify_calls == ["AAA"]
    assert provider.calls == []


def test_qualify_success_is_cached_per_symbol(env):
    provider = FakeProvider()
    ctx = _ctx(provider)
    _fetch(ctx, _row("15m"))
    _fetch(ctx, _row("1h"))
    assert provider.qualify_calls == ["AAA"]


def test_disconnected_client_that_cannot_reconnect_is_gateway_lost(env):
    provider = FakeProvider()
    provider.connected = False
    provider.connect_result = False
    ctx = _ctx(provider)
    with pytest.raises(item_mod.GatewayLost):
        _fetch(ctx, _row("15m"))
    assert "AAA" not in ctx.qualified  # never cache a verdict reached on a dead socket


def test_head_lookup_once_per_symbol_floors_the_window(env):
    provider = FakeProvider()
    provider.head_answer = (datetime(2016, 10, 18, 13, 30, tzinfo=UTC), None)
    ctx = _ctx(provider)
    _fetch(ctx, _row("15m"))
    _fetch(ctx, _row("1h"))
    assert provider.head_calls == ["AAA"]
    assert len(env.heads_recorded) == 1
    # Head snapped to midnight UTC so the listing day's own bars are still asked for.
    assert env.gap_calls[0].start == datetime(2016, 10, 18, tzinfo=UTC)
    assert env.gap_calls[1].start == datetime(2016, 10, 18, tzinfo=UTC)


def test_failed_head_lookup_is_not_retried_this_run(env):
    provider = FakeProvider()
    ctx = _ctx(provider)
    _fetch(ctx, _row("15m"))
    _fetch(ctx, _row("5m"))
    assert provider.head_calls == ["AAA"]
    assert env.heads_recorded == []


def test_no_head_lookup_for_single_request_timeframes_futures_or_tail_windows(env):
    provider = FakeProvider()
    ctx = _ctx(provider)
    _fetch(ctx, _row("1d"))  # 7300 days is one 1d request: the lookup would save nothing
    _fetch(
        ctx,
        _row("15m", symbol="ESZ6"),
        instrument=_instrument("ESZ6", AssetClass.FUTURES),
    )
    _fetch(ctx, _row("15m", symbol="BBB", latest=_COVERED_LATEST, status="ok"))
    assert provider.head_calls == []


def test_fresh_stored_head_floors_without_a_lookup(env):
    provider = FakeProvider()
    ctx = _ctx(provider, fresh_heads={"AAA": datetime(2015, 3, 2, 14, 30, tzinfo=UTC)})
    _fetch(ctx, _row("15m"))
    assert provider.head_calls == []
    assert env.gap_calls[0].start == datetime(2015, 3, 2, tzinfo=UTC)


def test_fx_fallback_derives_from_one_deep_1m_fetch_per_symbol(env):
    provider = FakeProvider(bars_by_tf={"1m": _bars("EURUSD", "1m", 6)})
    env.bars_1m = [
        {
            "timestamp": datetime(2026, 9, 1, 10, m, tzinfo=UTC),
            "open": 1.1,
            "high": 1.2,
            "low": 1.0,
            "close": 1.15,
            "volume": 10.0,
            "source": "ibkr",
        }
        for m in range(30)
    ]
    ctx = _ctx(provider)
    fx = _instrument("EURUSD", AssetClass.FX)
    first = _fetch(ctx, _row("5m", symbol="EURUSD"), instrument=fx)
    second = _fetch(ctx, _row("15m", symbol="EURUSD"), instrument=fx)

    deep_calls = [c for c in provider.calls if c["timeframe"] == "1m"]
    assert len(deep_calls) == 1
    assert deep_calls[0]["start"] == (_END - timedelta(days=pipeline._1M_DAYS_FX)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    by_series = {(p.coverage.timeframe, p.coverage.destination) for p in env.persist}
    assert ("1m", "grid") in by_series  # the deep fetch's own chunks
    assert ("5m", "grid") in by_series  # derived grid timeframe
    assert ("15m", "archive") in by_series  # derived archive timeframe
    assert first.status == second.status == "ok"


def test_fx_fallback_skipped_when_the_direct_fetch_stored_bars(env):
    provider = FakeProvider()
    _fetch(
        _ctx(provider),
        _row("5m", symbol="EURUSD"),
        instrument=_instrument("EURUSD", AssetClass.FX),
    )
    assert [c["timeframe"] for c in provider.calls] == ["5m"]


def test_per_contract_futures_route_through_fetch_per_contract(env):
    provider = FakeProvider()
    ctx = _ctx(provider, per_contract=True)
    outcome = _fetch(
        ctx,
        _row("1h", symbol="ESZ6"),
        instrument=_instrument("ESZ6", AssetClass.FUTURES),
    )
    assert len(env.per_contract) == 1
    assert env.per_contract[0]["timeframe"] == "1h"
    assert env.per_contract[0]["fetch_days"] == 7300
    assert provider.calls == []
    assert outcome.status == "ok" and outcome.n_bars == 12


def test_continuous_contract_only_for_deep_futures_windows(env):
    provider = FakeProvider()
    ctx = _ctx(provider)
    _fetch(ctx, _row("1d", symbol="ESZ6"), instrument=_instrument("ESZ6", AssetClass.FUTURES))
    _fetch(ctx, _row("1d"))
    assert [c["continuous"] for c in provider.calls] == [True, False]


def test_reconcile_runs_on_the_oldest_window_only(env):
    env.gaps = [
        (datetime(2010, 1, 4, tzinfo=UTC), datetime(2010, 1, 8, tzinfo=UTC)),
        (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 15, tzinfo=UTC)),
    ]
    provider = FakeProvider()
    _fetch(_ctx(provider), _row("15m"))
    assert len(provider.calls) == 2  # the two ranges are far apart: two windows
    assert provider.calls[0]["on_empty_history"] is not None
    assert provider.calls[1]["on_empty_history"] is None
    assert len(env.reconciled) == 1


# --- ports of tests/unit/scripts/test_historical_pipeline_d1_capture.py ------
# Named test_port_<source test name> so plan 08 can confirm coverage before deleting the
# source file. The lease cases (priority tier, lease timeout) are not ported: the lease is
# retired by plan 08 and the fetcher's singleton is FetcherLock (plan 02).


def _run_symbols(env, timeframes=("1d", "15m"), symbols=("AAA", "BBB", "CCC"), **ctx_kw):
    provider = FakeProvider()
    ctx = _ctx(provider, **ctx_kw)
    outcomes = [_fetch(ctx, _row(tf, symbol=s)) for s in symbols for tf in timeframes]
    return provider, ctx, outcomes


def test_port_capture_and_checkpoint_wiring(env):
    provider, ctx, outcomes = _run_symbols(env)
    assert all(o.status == "ok" for o in outcomes)
    assert len(provider.calls) == 6
    for call in provider.calls:
        assert call["on_request"] is not None
        assert call["fetch_run_id"] == _RUN_ID
        if call["timeframe"] == "1d":
            assert call["on_observation"] == ctx.sink.on_observation
        else:
            assert call.get("on_observation") is None
    # Every request is committed with its chunk; observations (1d only) flush per item.
    assert ctx.sink.total_observations == 6
    assert ctx.sink.flushes == 6
    taken = sum(len(p.requests) for p in env.persist)
    assert taken + ctx.sink.total_requests == 3 * 2 + 3  # 1d: SMART + venue, 15m: one
    assert sorted((s, tf) for s, tf, _ in env.marked) == [
        ("AAA", "15m"),
        ("AAA", "1d"),
        ("BBB", "15m"),
        ("BBB", "1d"),
        ("CCC", "15m"),
        ("CCC", "1d"),
    ]


def test_port_default_15m_is_archive_bound_and_1d_keeps_the_placeholder_path(env):
    _run_symbols(env)
    assert sorted(env.normalized) == [(s, "1d") for s in ("AAA", "BBB", "CCC")]
    answered = {(c.symbol, c.tf): c.answered for c in env.gap_calls}
    for symbol in ("AAA", "BBB", "CCC"):
        assert answered[(symbol, "15m")] == ("answered", symbol, "15m")
        assert answered[(symbol, "1d")] is None
    destinations = {(p.coverage.symbol, p.coverage.timeframe): p.writer for p in env.persist}
    for symbol in ("AAA", "BBB", "CCC"):
        assert destinations[(symbol, "15m")] is pipeline._insert_archive_rows
        assert destinations[(symbol, "1d")] is pipeline._insert_market_data_rows


def test_port_real_bars_only_skips_the_fill_and_reads_coverage_for_intraday(env):
    _, _, outcomes = _run_symbols(env, timeframes=("1d", "5m"), real_bars_only=True)
    # 5m is stored as the provider returned it; 1d still goes through the fill.
    assert sorted(env.normalized) == [("AAA", "1d"), ("BBB", "1d"), ("CCC", "1d")]
    answered = {(c.symbol, c.tf): c.answered for c in env.gap_calls}
    for symbol in ("AAA", "BBB", "CCC"):
        assert answered[(symbol, "5m")] == ("answered", symbol, "5m")
        assert answered[(symbol, "1d")] is None
    assert len(env.marked) == 6
    assert all(o.status == "ok" for o in outcomes)


def test_port_15m_always_asks_through_the_last_slot_end(env):
    provider, _, _ = _run_symbols(env, symbols=("AAA",))
    ends = {c["timeframe"]: c["end"] for c in provider.calls}
    assert ends["15m"] == datetime(2024, 1, 15, 0, 15, tzinfo=UTC)
    assert ends["1d"] == datetime(2024, 1, 15, tzinfo=UTC)  # 1d stays on the placeholder path


def test_port_flush_failure_fails_the_symbol_loudly(env):
    provider = FakeProvider()
    ctx = _ctx(provider)
    ctx.sink.fail_flush = True
    with pytest.raises(RuntimeError, match="D1 flush failed"):
        _fetch(ctx, _row("1d"))
    # Under the retry wrapper the same failure is an error outcome, not a crash.
    outcome = asyncio.run(
        fetch_item_with_retries(
            ctx,
            _instrument(),
            _row("1d"),
            gap_days=0,
            full_scan=False,
            config=_config(timeout_s=5.0),
            reconnect=_reconnects(),
        )
    )
    assert outcome.status == "error"
    assert "D1 flush failed" in (outcome.error or "")
