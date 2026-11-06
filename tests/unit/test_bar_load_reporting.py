"""Share-only restatement flags are reported and never fail a load; basis-change flags and
unselected slots do (D-191-N, 191-05; fourth review of 191-07, finding 2)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

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


def _summary(**counts) -> dict:
    """A nightly summary with every key the run initializes, the given counts set."""
    return dict.fromkeys(ops_bar_nightly._SUMMARY_KEYS, 0) | counts


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


def _bar(ts):
    return SimpleNamespace(timestamp=ts, open=1, high=1, low=1, close=1, volume=1)


class _PagedLeaf:
    """A leaf that reports each page through on_request then on_page, as AlpacaProvider does;
    `answers[timeframe]` is a list of pages, each a list of bars, or an Exception that fails the
    page after its failed row is reported."""

    def __init__(self, sink, answers, *, unfinished=False):
        self.sink = sink
        self.answers = answers
        self.unfinished = unfinished
        self.asked: list[tuple] = []

    async def connect(self):
        pass

    async def close(self):
        pass

    async def fetch_ohlcv(self, request, budget):
        self.asked.append((request.timeframe, request.start, request.end))
        pages = self.answers[request.timeframe]
        for index, page in enumerate(pages):
            record = SimpleNamespace(
                request_id=f"{request.timeframe}-{index}",
                answered_at=datetime(2026, 10, 9, 21, tzinfo=UTC),
                symbol=request.symbol,
                timeframe=request.timeframe,
                outcome="failed" if isinstance(page, Exception) else "bars",
            )
            self.sink.on_request(record)
            if isinstance(page, Exception):
                raise page
            self.sink.on_page(record, page)
        return SimpleNamespace(
            bars=[], next_window_start=request.start if self.unfinished else None
        )


class _Inner:
    """The RequestSink slice the nightly sink uses, recording what it buffered and wrote."""

    def __init__(self):
        self.buffered: list[str] = []
        self.written: list[str] = []
        self.noted: list[tuple[str, str]] = []
        self.outcomes: dict[str, str] = {}

    def on_request(self, record):
        self.buffered.append(record.request_id)
        self.outcomes[record.request_id] = record.outcome

    def take_requests(self, ids):
        taken = [rid for rid in self.buffered if rid in ids]
        self.buffered = [rid for rid in self.buffered if rid not in ids]
        return taken

    def note_partial(self, rid, text):
        self.noted.append((rid, text))

    def flush(self):
        self.written += self.buffered
        n, self.buffered = len(self.buffered), []
        return n

    def discard(self):
        n, self.buffered = len(self.buffered), []
        return n

    def pending(self):
        return len(self.buffered)


def _night(
    monkeypatch,
    answers,
    *,
    write=True,
    end=None,
    unfinished=False,
    store_fails=(),
    windows=None,
    skip_complete=False,
    answered=(),
):
    """Run the nightly over a paged fake leaf; returns (summary, inner sink, load calls). A 5m
    page whose request id is in `store_fails` raises in the load engine."""
    calls: list[tuple] = []

    def fake_series(conn, policy, symbol, frame, *, params, write, answered_at, request_rows):
        if request_rows and request_rows[0] in store_fails:
            raise RuntimeError("persist failed")
        calls.append(("5m", list(frame["t"]), request_rows, write))
        return LoadResult().plus(_flagged(len(frame))) if write else LoadResult(len(frame))

    def fake_frame(conn, symbol, frame, **kw):
        calls.append(("1d", list(frame["t"]), kw["request_rows"], kw["write"]))
        return LoadResult(n_offered=len(frame), n_new=len(frame))

    monkeypatch.setattr(ops_bar_nightly, "load_series", fake_series)
    monkeypatch.setattr(ops_bar_nightly, "load_frame", fake_frame)
    monkeypatch.setattr(ops_bar_nightly, "record_fetch_outcome", lambda *a, **k: None)
    monkeypatch.setattr(ops_bar_nightly, "_complete_asks", lambda *a: list(answered))
    inner = _Inner()
    sink = ops_bar_nightly._NightlySink(inner, _Conn(), provider="alpaca")
    policy = bar_load.LoadPolicy(vendor="alpaca", timeframe="5m", caller="x")
    now = datetime.now(UTC)
    summary = asyncio.run(
        ops_bar_nightly._run(
            _PagedLeaf(sink, answers, unfinished=unfinished),
            None,
            sink,
            policy,
            None,
            timedelta(minutes=30),
            ["SPY"],
            windows or [(now - timedelta(days=5), end or now - timedelta(minutes=20))],
            write,
            FetchBudget(deadline=now + timedelta(minutes=30), max_requests=500),
            skip_complete=skip_complete,
        )
    )
    return summary, inner, calls


_T1 = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)
_T2 = datetime(2026, 10, 9, 13, 35, tzinfo=UTC)


def test_nightly_summary_counts_flagged_series_and_stays_applied(monkeypatch):
    summary, _, _ = _night(monkeypatch, {"5m": [[_bar(_T1)]], "1d": [[]]})
    assert summary["flagged"] == 1 and summary["errors"] == 0
    line = ops_bar_nightly.summary_line(summary, apply=True)
    assert line.startswith("APPLIED") and "1 restatement-flagged" in line
    assert ops_bar_nightly.exit_code(summary) == 0
    clean = _summary(authored=4, raw_1d=4)
    assert ops_bar_nightly.summary_line(clean, apply=True).startswith("APPLIED")
    assert ops_bar_nightly.exit_code(clean) == 0


def test_each_page_commits_its_own_request_row_with_its_own_bars(monkeypatch):
    """Todo 596: a page's ledger row and that page's bars go to the load engine together (one
    transaction there), never the whole window's bars under one row or rows flushed apart."""
    summary, inner, calls = _night(monkeypatch, {"5m": [[_bar(_T1)], [_bar(_T2)]], "1d": [[]]})
    assert [(tf, rows) for tf, _, rows, _ in calls] == [
        ("5m", ["5m-0"]),
        ("5m", ["5m-1"]),
        ("1d", ["1d-0"]),
    ]
    assert [stamps for _, stamps, _, _ in calls][:2] == [[_T1], [_T2]]
    assert inner.written == [] and summary["pages"] == 3


def test_a_dry_run_writes_no_ledger_row(monkeypatch):
    """Todo 596: the nightly used to flush request rows without --apply."""
    summary, inner, calls = _night(
        monkeypatch, {"5m": [[_bar(_T1)], RuntimeError("boom")], "1d": [[]]}, write=False
    )
    assert inner.written == [] and inner.buffered == []
    assert all(not write for _, _, _, write in calls)
    assert summary["errors"] == 1


def test_a_failed_page_row_is_written_after_the_symbol(monkeypatch):
    summary, inner, calls = _night(
        monkeypatch, {"5m": [[_bar(_T1)], RuntimeError("boom")], "1d": [[]]}
    )
    assert inner.written == ["5m-1"]
    assert [rows for _, _, rows, _ in calls] == [["5m-0"], ["1d-0"]]  # 1d still asked
    assert summary["errors"] == 1 and ops_bar_nightly.exit_code(summary) == 1


def test_a_window_the_budget_left_unfinished_fails_the_night(monkeypatch):
    summary, _, _ = _night(monkeypatch, {"5m": [[_bar(_T1)]], "1d": [[]]}, unfinished=True)
    assert summary["unfinished"] == 2
    assert "2 windows unfinished" in ops_bar_nightly.summary_line(summary, apply=True)
    assert ops_bar_nightly.exit_code(summary) == 1


def test_ops_bar_load_uses_the_shared_status():
    assert ops_bar_load.load_status is load_status


def test_unselected_slots_are_reported_and_fail_the_night():
    ingress = IngressResult(4, 4, 0, 0, 1, n_unselected=3)
    result = LoadResult().plus(ingress).plus(ingress)
    assert result.n_unselected == 6
    status = load_status(apply=True, unselected=6)
    assert status != "APPLIED" and "UNSELECTED" in status
    assert load_status(apply=False, unselected=6) == "PLANNED"
    summary = _summary(authored=4, unselected=6)
    assert "6 unselected" in ops_bar_nightly.summary_line(summary, apply=True)
    assert ops_bar_nightly.exit_code(summary) == 1


def test_nightly_holds_back_incomplete_bars_and_records_them_on_the_page_row(monkeypatch):
    """Second review of 191-07, finding 5: the Alpaca leaf has no forming-bar rule, so the
    nightly splits every page against the time it asked; a bar still forming is not offered to
    raw and its values go onto the request row of the page that served it."""
    now = datetime.now(UTC)
    forming = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
    summary, inner, calls = _night(
        monkeypatch,
        {"5m": [[_bar(_T1), _bar(forming)]], "1d": [[]]},
        end=now + timedelta(days=1),
    )
    assert summary["partial"] == 1 and summary["errors"] == 0
    assert calls[0][1] == [_T1]
    [(request_id, text)] = inner.noted
    assert request_id == "5m-0" and forming.isoformat() in text
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
    summary = _summary(authored=78, flagged=1, basis_flagged=1)
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
    sink.stored(_record("CCO", "5m", "bars", t))  # answered pages count once stored
    sink.stored(_record("CCO", "5m", "no_data", t + timedelta(minutes=2)))
    sink.on_request(_record("CCO", "1d", "timeout", t + timedelta(minutes=1)))
    assert sink.flush(write=True) == 3
    assert sorted(written) == [
        ("CCO", "1d", "error", 41, "alpaca"),
        ("CCO", "5m", "no_data", 42, "alpaca"),
    ]
    assert conn.statements == ["SET LOCAL ROLE bar_derivation_writer"]
    sink.flush(write=True)
    assert len(written) == 2  # nothing left to record


def test_a_late_arriving_older_record_does_not_move_the_status_back(monkeypatch):
    sink, written, _ = _sink(monkeypatch)
    t = datetime(2026, 10, 30, 4, 40, tzinfo=UTC)
    sink.stored(_record("CCO", "5m", "no_data", t + timedelta(minutes=5)))
    sink.stored(_record("CCO", "5m", "bars", t))
    sink.flush(write=True)
    assert written == [("CCO", "5m", "no_data", 45, "alpaca")]


def test_no_status_is_written_while_request_rows_are_still_buffered(monkeypatch):
    sink, written, conn = _sink(monkeypatch, pending=2)
    sink.on_request(_record("CCO", "5m", "bars", datetime(2026, 10, 30, 4, 40, tzinfo=UTC)))
    sink.flush(write=True)
    assert written == [] and conn.statements == []


def test_an_answered_page_whose_store_failed_moves_no_status(monkeypatch):
    """A page reported answered whose bars then failed to store leaves no request row, so it
    must not become the series' newest fetch status either (review of todo 596 step 1)."""
    sink, written, _ = _sink(monkeypatch)
    sink.on_request(_record("CCO", "5m", "bars", datetime(2026, 10, 30, 4, 40, tzinfo=UTC)))
    sink.flush(write=True)
    assert written == []


def test_a_page_row_missing_from_the_buffer_is_loud():
    """Bars never commit without their ledger row: take() wants exactly one buffered row."""
    sink = ops_bar_nightly._NightlySink(_Inner(), _Conn(), provider="alpaca")
    with pytest.raises(RuntimeError, match="expected 1"):
        sink.take("never-buffered")


def test_a_page_whose_store_failed_writes_a_failed_row_not_its_answered_row(monkeypatch):
    """Review of todo 596 step 1: an answered (possibly terminal) row must never be written
    without its bars; a failed row for the page takes its place and the ask reads incomplete."""
    summary, inner, calls = _night(
        monkeypatch, {"5m": [[_bar(_T1)], [_bar(_T2)]], "1d": [[]]}, store_fails=("5m-1",)
    )
    assert "5m-1" not in inner.written
    [failed] = inner.written
    assert inner.outcomes[failed] == "failed"
    assert [rows for _, _, rows, _ in calls] == [["5m-0"], ["1d-0"]]  # 1d still asked
    assert summary["errors"] == 1 and summary["pages"] == 2  # 5m page 0 and the 1d page


def test_a_vendor_page_always_fits_one_load_chunk():
    """The page row commits with all of its bars only while a vendor page fits one chunk."""
    from services.bar_load import CHUNK_ROWS
    from src.providers import alpaca

    assert alpaca._PAGE_LIMIT <= CHUNK_ROWS  # noqa: SLF001


def test_history_windows_cut_at_each_new_year_outside_every_session():
    from datetime import date

    windows = ops_bar_nightly.history_windows(date(2016, 1, 4), date(2018, 3, 1))
    assert [(a.date(), b.date()) for a, b in windows] == [
        (date(2016, 1, 4), date(2017, 1, 1)),
        (date(2017, 1, 1), date(2018, 1, 1)),
        (date(2018, 1, 1), date(2018, 3, 1)),
    ]
    # 06:00 UTC: after the latest extended-hours bar (01:00 UTC in winter), before the earliest
    assert {(a.hour, a.tzinfo) for pair in windows for a in pair} == {(6, UTC)}
    with pytest.raises(ValueError, match="precede"):
        ops_bar_nightly.history_windows(date(2018, 1, 1), date(2018, 1, 1))


def test_a_rerun_skips_windows_a_complete_ask_already_answered(monkeypatch):
    """The re-ask's resume rule: windows a complete ask holds are not asked again."""
    w1 = (datetime(2016, 1, 4, tzinfo=UTC), datetime(2017, 1, 1, tzinfo=UTC))
    w2 = (datetime(2017, 1, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC))
    summary, _, calls = _night(
        monkeypatch,
        {"5m": [[_bar(_T1)]], "1d": [[]]},
        windows=[w1, w2],
        skip_complete=True,
        answered=[(w1[0] - timedelta(days=1), w1[1])],
    )
    assert summary["skipped"] == 2 and summary["pages"] == 2  # w1 skipped on both timeframes
    assert len(calls) == 2


def test_a_failed_window_does_not_abandon_the_symbols_other_windows(monkeypatch):
    w1 = (datetime(2016, 1, 4, tzinfo=UTC), datetime(2017, 1, 1, tzinfo=UTC))
    w2 = (datetime(2017, 1, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC))
    answers = {"5m": [RuntimeError("boom")], "1d": [[]]}
    summary, _, calls = _night(monkeypatch, answers, windows=[w1, w2])
    assert summary["errors"] == 2  # both 5m windows failed and were each counted
    assert [tf for tf, *_ in calls] == ["1d", "1d"]  # the 1d windows were still asked
