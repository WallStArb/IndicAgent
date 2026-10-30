"""Share-only restatement flags are reported and never fail a load; basis-change flags and
unselected slots do (D-191-N, 191-05; fourth review of 191-07, finding 2)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from scripts.ops.bars import ops_bar_load, ops_bar_nightly
from services import bar_load
from services.bar_load import LoadResult, load_status
from services.ohlcv_ingress_contract import FlaggedSeries, IngressResult
from src.intelligence.bars.restatement import Restatement
from src.providers.base import FetchBudget


def _flagged(n: int) -> IngressResult:
    flag = FlaggedSeries(
        "SPY", "5m", "alpaca", "sip_rth", uuid.uuid4(), Restatement(n, n, 1.0, ("share",))
    )
    return IngressResult(n, 0, n, 0, 0, flagged=(flag,))


def test_load_result_counts_flagged_series_across_chunks():
    result = LoadResult().plus(_flagged(5)).plus(_flagged(3))
    assert (result.n_changed, result.n_flagged_series) == (8, 2)
    clean = LoadResult().plus(IngressResult(4, 4, 0, 0, 0))
    assert clean.n_flagged_series == 0


def test_load_status_is_applied_whatever_was_flagged():
    assert load_status(apply=False) == "PLANNED"
    assert load_status(apply=True) == "APPLIED"


class _Cursor:
    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.statements.append(sql)


class _Conn:
    """The slice of a psycopg connection the ledger writes use: a transaction and a cursor."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def transaction(self):
        return _Cursor(self)

    def cursor(self):
        return _Cursor(self)


def test_nightly_summary_counts_flagged_series_and_stays_applied(monkeypatch):
    def fake_series(conn, policy, symbol, frame, *, params, write, answered_at=None):
        return LoadResult().plus(_flagged(len(frame)))

    def fake_frame(conn, symbol, frame, **kw):
        return LoadResult(n_offered=len(frame), n_new=len(frame))

    monkeypatch.setattr(ops_bar_nightly, "load_series", fake_series)
    monkeypatch.setattr(ops_bar_nightly, "load_frame", fake_frame)

    page = SimpleNamespace(
        bars=[
            SimpleNamespace(
                timestamp=pd.Timestamp("2026-10-09 13:30", tz="UTC"),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        ]
    )

    class Leaf:
        async def connect(self):
            pass

        async def close(self):
            pass

        async def fetch_ohlcv(self, request, budget):
            return page

    sink = SimpleNamespace(flush=lambda: 0)
    policy = bar_load.LoadPolicy(vendor="alpaca", timeframe="5m", caller="x")
    summary = asyncio.run(
        ops_bar_nightly._run(
            Leaf(),
            None,
            sink,
            policy,
            None,
            timedelta(minutes=30),
            ["SPY"],
            None,
            None,
            True,
            FetchBudget(deadline=datetime.now(UTC) + timedelta(minutes=30), max_requests=500),
        )
    )
    assert summary["flagged"] == 1 and summary["errors"] == 0
    line = ops_bar_nightly.summary_line(summary, apply=True)
    assert line.startswith("APPLIED") and "1 restatement-flagged" in line
    assert ops_bar_nightly.exit_code(summary) == 0
    clean = {"authored": 4, "raw_1d": 4, "errors": 0, "flagged": 0, "unselected": 0}
    assert ops_bar_nightly.summary_line(clean, apply=True).startswith("APPLIED")
    assert ops_bar_nightly.exit_code(clean) == 0


def test_ops_bar_load_uses_the_shared_status():
    assert ops_bar_load.load_status is load_status


def test_unselected_slots_are_reported_and_fail_the_night():
    ingress = IngressResult(4, 4, 0, 0, 1, n_unselected=3)
    result = LoadResult().plus(ingress).plus(ingress)
    assert result.n_unselected == 6
    status = load_status(apply=True, unselected=6)
    assert status != "APPLIED" and "UNSELECTED" in status
    assert load_status(apply=False, unselected=6) == "PLANNED"
    summary = {"authored": 4, "raw_1d": 0, "errors": 0, "flagged": 0, "unselected": 6}
    assert "6 unselected" in ops_bar_nightly.summary_line(summary, apply=True)
    assert ops_bar_nightly.exit_code(summary) == 1


def test_nightly_holds_back_incomplete_bars_and_records_them_on_the_request(monkeypatch):
    """Second review of 191-07, finding 5: the Alpaca leaf has no forming-bar rule, so the
    nightly splits every page against the time it asked; a bar still forming is not offered to
    raw and its values go onto the window's last request row."""
    offered: list[pd.DataFrame] = []

    def fake_series(conn, policy, symbol, frame, *, params, write, answered_at=None):
        offered.append(frame)
        return LoadResult(n_offered=len(frame))

    monkeypatch.setattr(ops_bar_nightly, "load_series", fake_series)
    monkeypatch.setattr(ops_bar_nightly, "load_frame", lambda *a, **k: LoadResult())
    now = datetime.now(UTC)
    forming = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)

    def bar(ts):
        return SimpleNamespace(timestamp=ts, open=1, high=1, low=1, close=1, volume=1)

    pages = {
        "5m": SimpleNamespace(bars=[bar(datetime(2026, 10, 9, 13, 30, tzinfo=UTC)), bar(forming)]),
        "1d": SimpleNamespace(bars=[]),
    }

    class Leaf:
        def __init__(self, sink):
            self.sink = sink

        async def connect(self):
            pass

        async def close(self):
            pass

        async def fetch_ohlcv(self, request, budget):
            self.sink.on_request(
                SimpleNamespace(
                    request_id=f"req-{request.timeframe}",
                    answered_at=now,
                    symbol=request.symbol,
                    timeframe=request.timeframe,
                    outcome="bars",
                )
            )
            return pages[request.timeframe]

    noted: list[tuple[str, str]] = []
    inner = SimpleNamespace(
        on_request=lambda record: None,
        note_partial=lambda rid, text: noted.append((rid, text)),
        flush=lambda: 0,
        pending=lambda: 0,
    )
    statuses: list[tuple] = []
    monkeypatch.setattr(
        ops_bar_nightly,
        "record_fetch_outcome",
        lambda cur, symbol, timeframe, status, at, *, provider: statuses.append(
            (symbol, timeframe, status, provider)
        ),
    )
    sink = ops_bar_nightly._NightlySink(inner, _Conn(), provider="alpaca")
    policy = bar_load.LoadPolicy(vendor="alpaca", timeframe="5m", caller="x")
    summary = asyncio.run(
        ops_bar_nightly._run(
            Leaf(sink),
            None,
            sink,
            policy,
            None,
            timedelta(minutes=30),
            ["SPY"],
            None,
            now + timedelta(days=1),
            True,
            FetchBudget(deadline=now + timedelta(minutes=30), max_requests=500),
        )
    )
    assert summary["partial"] == 1 and summary["errors"] == 0
    assert list(offered[0]["t"]) == [datetime(2026, 10, 9, 13, 30, tzinfo=UTC)]
    [(request_id, text)] = noted
    assert request_id == "req-5m" and forming.isoformat() in text
    assert "1 incomplete bars held back" in ops_bar_nightly.summary_line(summary, apply=True)


def _basis(n: int) -> IngressResult:
    flag = FlaggedSeries(
        "SPY",
        "5m",
        "ibkr",
        "named",
        uuid.uuid4(),
        Restatement(n, n, 1.0, ("share", "price_ratio"), ratio=0.5),
    )
    return IngressResult(n, 0, n, 0, 0, flagged=(flag,))


def test_a_basis_change_flag_makes_the_load_partial_and_fails_the_night():
    result = LoadResult().plus(_basis(78)).plus(_flagged(5))
    assert (result.n_flagged_series, result.n_basis_flagged) == (2, 1)
    status = load_status(apply=True, basis_flagged=1)
    assert status.startswith("PARTIAL") and "ops_restatement_review" in status
    summary = {
        "authored": 78,
        "raw_1d": 0,
        "errors": 0,
        "flagged": 1,
        "basis_flagged": 1,
        "unselected": 0,
    }
    assert ops_bar_nightly.summary_line(summary, apply=True).startswith("PARTIAL")
    assert ops_bar_nightly.exit_code(summary) == 1


def test_superseded_offers_are_counted_across_chunks():
    ingress = IngressResult(4, 0, 0, 0, 0, n_superseded=4)
    assert LoadResult().plus(ingress).plus(ingress).n_superseded == 8


def _record(symbol, timeframe, outcome, at):
    return SimpleNamespace(
        request_id=f"{symbol}-{timeframe}-{at.minute}",
        answered_at=at,
        symbol=symbol,
        timeframe=timeframe,
        outcome=outcome,
    )


def _sink(monkeypatch, *, pending=0):
    written: list[tuple] = []
    monkeypatch.setattr(
        ops_bar_nightly,
        "record_fetch_outcome",
        lambda cur, symbol, timeframe, status, at, *, provider: written.append(
            (symbol, timeframe, status, at.minute, provider)
        ),
    )
    inner = SimpleNamespace(
        on_request=lambda record: None, flush=lambda: 3, pending=lambda: pending
    )
    conn = _Conn()
    return ops_bar_nightly._NightlySink(inner, conn, provider="alpaca"), written, conn


def test_a_flush_records_the_newest_outcome_of_each_series_as_the_ledger_status(monkeypatch):
    sink, written, conn = _sink(monkeypatch)
    t = datetime(2026, 10, 30, 4, 40, tzinfo=UTC)
    sink.on_request(_record("CCO", "5m", "bars", t))
    sink.on_request(_record("CCO", "5m", "no_data", t + timedelta(minutes=2)))
    sink.on_request(_record("CCO", "1d", "timeout", t + timedelta(minutes=1)))
    assert sink.flush() == 3
    assert sorted(written) == [
        ("CCO", "1d", "error", 41, "alpaca"),
        ("CCO", "5m", "no_data", 42, "alpaca"),
    ]
    assert conn.statements == ["SET LOCAL ROLE bar_derivation_writer"]
    sink.flush()
    assert len(written) == 2  # nothing left to record


def test_a_late_arriving_older_record_does_not_move_the_status_back(monkeypatch):
    sink, written, _ = _sink(monkeypatch)
    t = datetime(2026, 10, 30, 4, 40, tzinfo=UTC)
    sink.on_request(_record("CCO", "5m", "no_data", t + timedelta(minutes=5)))
    sink.on_request(_record("CCO", "5m", "bars", t))
    sink.flush()
    assert written == [("CCO", "5m", "no_data", 45, "alpaca")]


def test_no_status_is_written_while_request_rows_are_still_buffered(monkeypatch):
    sink, written, conn = _sink(monkeypatch, pending=2)
    sink.on_request(_record("CCO", "5m", "bars", datetime(2026, 10, 30, 4, 40, tzinfo=UTC)))
    sink.flush()
    assert written == [] and conn.statements == []
