"""UniverseMembershipWriter and corpus_universe on synthetic inputs (no database)."""

from __future__ import annotations

import csv
import math
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import corpus_universe as cu
from services import universe_membership_writer as w


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _pages(as_of: date, **overrides) -> list[dict]:
    """A complete capture: one OK page per list, no next_url."""
    base = {"page": 1, "http_status": 200, "status": "OK", "next_url": None}
    return [
        {**base, "request_key": f"{as_of.isoformat()}@{kind}", **overrides.get(kind, {})}
        for kind in ("active", "inactive")
    ]


def test_month_ends_through_are_complete_nyse_month_ends():
    ends = w.month_ends_through(date(2020, 3, 15))
    assert ends[-1] == date(2020, 2, 28)  # March is partial: no March month-end yet
    assert date(2020, 1, 31) in ends and date(2019, 12, 31) in ends
    assert w.month_ends_through(date(2020, 3, 31))[-1] == date(2020, 3, 31)
    assert w.month_ends_through(date(2003, 9, 30)) == [date(2003, 9, 30)]


def test_histories_group_by_symbol_in_order_and_carry_splits():
    rec = [
        ("A", date(2020, 1, 2), 10.0, 100.0),
        ("A", date(2020, 1, 3), 11.0, 200.0),
        ("B", date(2020, 1, 2), 5.0, 50.0),
    ]
    split = w.SplitFactor(date(2020, 6, 1), 0.05)
    hist = w.histories_from_records(rec, {"A": [split]})
    assert sorted(hist) == ["A", "B"] and len(hist["A"].days) == 2
    assert hist["A"].close.tolist() == [10.0, 11.0]
    assert hist["A"].splits == (split,) and hist["B"].splits == ()


def test_null_volume_or_close_becomes_nan_not_a_member():
    from src.intelligence.universe_membership import decide

    days = _weekdays(date(2020, 1, 6), 60)
    rec = [("A", d, 10.0, None if i == 5 else 2e5) for i, d in enumerate(days)]
    hist = w.histories_from_records(rec)["A"]
    assert math.isnan(hist.volume[5])
    assert decide(hist, days[-1], "CS", False) is None
    nan_close = w.histories_from_records([("A", days[0], None, 1.0)])["A"]
    assert math.isnan(nan_close.close[0])


# --- I3: snapshot completeness -------------------------------------------------------------


def test_complete_snapshot_has_no_problem():
    assert w.snapshot_problem(date(2020, 1, 31), _pages(date(2020, 1, 31))) is None


@pytest.mark.parametrize("missing", ["active", "inactive"])
def test_snapshot_needs_both_lists(missing):
    as_of = date(2020, 1, 31)
    pages = [p for p in _pages(as_of) if not p["request_key"].endswith(missing)]
    assert f"@{missing} is not captured" in w.snapshot_problem(as_of, pages)


def test_snapshot_pages_must_be_contiguous_from_one():
    as_of = date(2020, 1, 31)
    pages = _pages(as_of, active={"page": 2})
    assert "are not 1..1" in w.snapshot_problem(as_of, pages)
    two = [
        {
            "request_key": f"{as_of}@active",
            "page": n,
            "http_status": 200,
            "status": "OK",
            "next_url": "u" if n == 1 else None,
        }
        for n in (1, 3)
    ] + _pages(as_of)[1:]
    assert "are not 1..2" in w.snapshot_problem(as_of, two)


def test_snapshot_last_page_must_have_no_next_url():
    as_of = date(2020, 1, 31)
    msg = w.snapshot_problem(as_of, _pages(as_of, inactive={"next_url": "https://x?cursor=1"}))
    assert "truncated capture" in msg


def test_snapshot_non_last_page_needs_next_url():
    as_of = date(2020, 1, 31)
    pages = [
        {
            "request_key": f"{as_of}@active",
            "page": n,
            "http_status": 200,
            "status": "OK",
            "next_url": None,
        }
        for n in (1, 2)
    ] + _pages(as_of)[1:]
    assert "no next_url" in w.snapshot_problem(as_of, pages)


@pytest.mark.parametrize("bad", [{"status": "ERROR"}, {"http_status": 500}, {"status": None}])
def test_snapshot_pages_must_be_ok(bad):
    as_of = date(2020, 1, 31)
    assert "status" in w.snapshot_problem(as_of, _pages(as_of, active=bad))


# --- build with a connection double --------------------------------------------------------


class _Conn:
    """asyncpg connection double answering the writer's queries from plain data."""

    def __init__(
        self,
        *,
        ledger=(),
        month_ends=(),
        pages=None,
        symbols=("AAA", "PPP", "THIN", "DEAD"),
        inactive=1,
        types=None,
        bars=None,
        splits=(),
        spans=(),
        seed=(),
        stale=(),
    ):
        self.ledger = list(ledger)
        self.pages = pages if pages is not None else {m: _pages(m) for m in month_ends}
        self.symbols, self.inactive = list(symbols), inactive
        self.types = types or {"AAA": "CS", "PPP": "PFD", "THIN": "CS", "DEAD": "CS"}
        self.bars, self.splits, self.spans = bars or {}, list(splits), list(spans)
        self.seed = list(seed)
        self.stale = list(stale)
        self.executemany = AsyncMock()
        self.copy_records_to_table = AsyncMock()

    async def fetch(self, sql, *args):
        if sql == w._LEDGER_SQL:
            return self.ledger
        if sql == w._SNAPSHOT_PAGES_SQL:
            return self.pages.get(args[0], [])
        if sql == w._PLACED_SYMBOLS_SQL:
            return [{"symbol": s} for s in self.symbols]
        if sql == w._MEMBERS_AT_SQL:
            return [{"symbol": s} for s in self.seed]
        if sql == w._TYPES_SQL:
            return [{"symbol": s, "security_type": t} for s, t in self.types.items()]
        if sql == w._BARS_SQL:
            return [(s, d, c, v) for s, rows in self.bars.items() for d, c, v in rows]
        if sql == w._SPLITS_SQL:
            return self.splits
        if sql == w._STALE_SPLITS_SQL:
            return self.stale
        if sql == w._SPAN_END_SQL:
            return self.spans
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql == w._INACTIVE_PLACED_SQL:
            return self.inactive
        raise AssertionError(sql)


def _writer(through: date, tmp_path, apply=False):
    return w.UniverseMembershipWriter("dsn", through, apply, tmp_path)


def _bars(days, close=10.0, dollars=2e6):
    return [(d, close, dollars / close) for d in days]


DAYS = _weekdays(date(2003, 9, 10), 90)  # through 2003-12-30; 2003-12-31 is day 91
DEC31 = date(2003, 12, 31)
DAYS_TO_DEC31 = _weekdays(date(2003, 9, 10), 91)
SEP_DEC = w.month_ends_through(DEC31)


async def test_missing_or_truncated_snapshot_fails_loudly_and_writes_nothing(tmp_path):
    conn = _Conn(pages={})
    with pytest.raises(RuntimeError, match="is not captured"):
        await _writer(date(2003, 9, 30), tmp_path)._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()
    bad = {m: _pages(m, active={"next_url": "more"}) for m in SEP_DEC}
    with pytest.raises(RuntimeError, match="truncated"):
        await _writer(DEC31, tmp_path)._build_and_write(_Conn(pages=bad))


async def test_foreign_rule_id_refuses_extension(tmp_path):
    conn = _Conn(ledger=[{"as_of": date(2020, 1, 31), "rule_id": "other", "n_members": 5}])
    with pytest.raises(RuntimeError, match="built under rule"):
        await _writer(date(2020, 3, 31), tmp_path)._build_and_write(conn)


async def test_up_to_date_ledger_writes_nothing(tmp_path):
    ledger = [{"as_of": date(2003, 9, 30), "rule_id": w.RULE_ID, "n_members": 0}]
    assert (
        await _writer(date(2003, 9, 30), tmp_path)._build_and_write(_Conn(ledger=ledger)) is False
    )


async def test_build_writes_ledger_for_empty_early_months_and_members_after(tmp_path):
    conn = _Conn(
        month_ends=SEP_DEC,
        bars={s: _bars(DAYS_TO_DEC31) for s in ("AAA", "PPP")}
        | {"THIN": _bars(DAYS_TO_DEC31, dollars=1e5)},
    )
    assert await _writer(DEC31, tmp_path)._build_and_write(conn) is True
    ledger = conn.executemany.call_args.args[1]
    assert [(m, n) for m, _, n in ledger] == [
        (date(2003, 9, 30), 0),
        (date(2003, 10, 31), 0),
        (date(2003, 11, 28), 0),
        (DEC31, 1),
    ]
    records = conn.copy_records_to_table.call_args.kwargs["records"]
    assert [(r[0], r[1], r[2], r[6]) for r in records] == [(DEC31, "AAA", "CS", True)]


async def test_run_with_no_member_and_no_prior_members_fails_loudly(tmp_path):
    conn = _Conn(month_ends=[date(2003, 9, 30)], bars={"AAA": _bars(DAYS)})
    with pytest.raises(RuntimeError, match="no member"):
        await _writer(date(2003, 9, 30), tmp_path)._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()
    conn.executemany.assert_not_called()


async def test_resume_after_a_month_with_members_requires_members_every_month(tmp_path):
    # I2: the ledger already holds a month with members, so an empty new month is a failed build
    # even though no new month has members ("first" over the new months alone would miss it).
    ledger = [{"as_of": date(2003, 12, 31), "rule_id": w.RULE_ID, "n_members": 1}]
    conn = _Conn(ledger=ledger, month_ends=[date(2004, 1, 30)], seed=["AAA"], bars={"AAA": []})
    with pytest.raises(RuntimeError, match="2004-01-30"):
        await _writer(date(2004, 1, 30), tmp_path)._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()


async def test_resume_seeds_hysteresis_from_the_last_built_month(tmp_path):
    days = _weekdays(date(2003, 9, 10), 135)
    jan30 = [d for d in days if d <= date(2004, 1, 30)][-1]
    assert jan30 == date(2004, 1, 30)
    # 700k a day: below the entry floor, above the exit floor
    ledger = [{"as_of": DEC31, "rule_id": w.RULE_ID, "n_members": 1}]
    bars = {"AAA": _bars(days, dollars=7e5)}
    kept = _Conn(ledger=ledger, month_ends=[jan30], seed=["AAA"], bars=bars)
    assert await _writer(jan30, tmp_path)._build_and_write(kept) is True
    records = kept.copy_records_to_table.call_args.kwargs["records"]
    assert [(r[1], r[6]) for r in records] == [("AAA", False)]
    fresh = _Conn(ledger=ledger, month_ends=[jan30], seed=[], bars=bars)
    with pytest.raises(RuntimeError, match="no member"):
        await _writer(jan30, tmp_path)._build_and_write(fresh)


# --- C1: as-traded price test --------------------------------------------------------------


def _split_row(symbol, effective, factor):
    return {
        "symbol": symbol,
        "effective_date": effective,
        "factor": factor,
        "recorded_at": datetime(2025, 1, 1, tzinfo=UTC),
        "inferred_by": "calendar_audit",
        "rows_file": False,
    }


async def test_future_reverse_split_does_not_admit_a_sub_dollar_name(tmp_path):
    # canonical stores 0.40 / 0.05 = 8.0 (a 1:20 reverse split after t divides old prices by 0.05)
    conn = _Conn(
        month_ends=SEP_DEC,
        symbols=("PENNY", "RICH", "DEAD"),
        types={"PENNY": "CS", "RICH": "CS", "DEAD": "CS"},
        bars={
            "PENNY": _bars(DAYS_TO_DEC31, close=8.0, dollars=2e6),
            "RICH": _bars(DAYS_TO_DEC31, close=0.5, dollars=2e6),  # as traded: 5.0
            "DEAD": _bars(DAYS_TO_DEC31, close=10.0, dollars=2e6),
        },
        splits=[
            _split_row("PENNY", date(2004, 6, 1), 0.05),
            _split_row("RICH", date(2004, 6, 1), 10.0),
        ],
    )
    await _writer(DEC31, tmp_path)._build_and_write(conn)
    records = conn.copy_records_to_table.call_args.kwargs["records"]
    by_symbol = {r[1]: r for r in records}
    assert set(by_symbol) == {"RICH", "DEAD"}
    assert by_symbol["RICH"][4] == pytest.approx(5.0)  # the stored close is as traded


async def test_split_before_t_is_not_undone(tmp_path):
    conn = _Conn(
        month_ends=SEP_DEC,
        symbols=("OLD", "DEAD"),
        types={"OLD": "CS", "DEAD": "CS"},
        bars={"OLD": _bars(DAYS_TO_DEC31, close=0.5), "DEAD": _bars(DAYS_TO_DEC31)},
        splits=[_split_row("OLD", date(2003, 10, 1), 10.0)],  # effective before DEC31
    )
    await _writer(DEC31, tmp_path)._build_and_write(conn)
    records = conn.copy_records_to_table.call_args.kwargs["records"]
    assert {r[1] for r in records} == {"DEAD"}  # 0.5 at t is as traded: below the $1 floor


# --- L1, L3 --------------------------------------------------------------------------------


async def test_survivor_only_placement_is_refused(tmp_path):
    conn = _Conn(month_ends=SEP_DEC, inactive=0, bars={"AAA": _bars(DAYS_TO_DEC31)})
    with pytest.raises(RuntimeError, match="survivor-only"):
        await _writer(DEC31, tmp_path)._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()


async def test_member_whose_bars_stop_before_its_span_is_reported(tmp_path):
    # AAA is a member at 2003-12-31 only if it has a bar that day, so make it a member in
    # December and then run the build to 2004-02-27 with its bars stopping at 2003-12-31
    days = _weekdays(date(2003, 9, 10), 91)
    ends = w.month_ends_through(date(2004, 2, 27))
    ledger_through = date(2004, 2, 27)
    conn = _Conn(
        month_ends=ends,
        symbols=("AAA", "DEAD"),
        types={"AAA": "CS", "DEAD": "CS"},
        bars={"AAA": _bars(days), "DEAD": _bars(days, dollars=1e5)},
        spans=[{"symbol": "AAA", "open_span": True, "span_end": None}],
    )
    # AAA stops after December: January and February have no member, a failed build, but the
    # report is written first so the vanished name is on record
    with pytest.raises(RuntimeError, match="no member"):
        await _writer(ledger_through, tmp_path)._build_and_write(conn)
    with (tmp_path / "vanished_without_final_bar.csv").open() as handle:
        rows = list(csv.reader(handle))
    assert rows[1][0] == "AAA" and rows[1][1] == "2003-12-31"


async def test_split_recorded_after_the_last_derivation_refuses_the_build(tmp_path):
    stale = [
        {
            "symbol": "RICH",
            "latest_action": datetime(2025, 3, 1, tzinfo=UTC),
            "latest_digest": datetime(2025, 1, 1, tzinfo=UTC),
        }
    ]
    conn = _Conn(
        month_ends=SEP_DEC,
        symbols=("RICH", "DEAD"),
        types={"RICH": "CS", "DEAD": "CS"},
        bars={"RICH": _bars(DAYS_TO_DEC31, close=0.5), "DEAD": _bars(DAYS_TO_DEC31)},
        splits=[_split_row("RICH", date(2004, 6, 1), 10.0)],
        stale=stale,
    )
    with pytest.raises(RuntimeError, match=r"not current with the splits.*RICH"):
        await _writer(DEC31, tmp_path)._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()
    conn.executemany.assert_not_called()


def test_stale_guard_reads_every_corporate_action_row_not_only_current_ones():
    # a superseding or void row is a change canonical has not seen either: the guard reads the
    # base table, and a symbol with actions but no 1d digest is stale too
    assert "FROM corporate_action ca" in w._STALE_SPLITS_SQL
    assert "corporate_action_current" not in w._STALE_SPLITS_SQL
    assert "d.computed_at IS NULL OR max(ca.recorded_at) > d.computed_at" in w._STALE_SPLITS_SQL
    assert "timeframe = '1d'" in w._STALE_SPLITS_SQL


def test_split_set_is_the_daily_rules_with_no_time_filter():
    assert "corporate_action_current" in w._SPLITS_SQL and "recorded_at" not in w._SPLITS_SQL


async def test_operator_correction_rows_are_not_undone(tmp_path):
    # an incumbent route correction (calendar_audit from an operator rows file) is not a market
    # split: is_market_split rejects it, as the daily rule does
    conn = _Conn(
        symbols=("X",),
        splits=[{**_split_row("X", date(2004, 6, 1), 10.0), "rows_file": True}],
    )
    assert await w.UniverseMembershipWriter._splits(conn, ["X"]) == {}


def _cursor_conn(ledger_row, instruments=()):
    cur = MagicMock()
    cur.fetchone.return_value = ledger_row
    cur.fetchall.return_value = list(instruments)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def test_corpus_universe_empty_ledger_fails_loudly():
    with pytest.raises(cu.UniverseMembershipEmptyError):
        cu.corpus_universe(_cursor_conn((0, 0, None)))


def test_corpus_universe_ledger_without_rows_fails_loudly():
    with pytest.raises(cu.UniverseMembershipEmptyError):
        cu.corpus_universe(_cursor_conn((3, 1, date(2020, 3, 31)), []))


def test_corpus_universe_mixed_rule_ids_fail():
    with pytest.raises(RuntimeError, match="mixes 2 rule ids"):
        cu.corpus_universe(_cursor_conn((3, 2, date(2020, 3, 31))))


def test_corpus_universe_builds_instruments(monkeypatch):
    seen = []
    monkeypatch.setattr(
        cu, "instrument_from_instruments_row", lambda *row: seen.append(row) or row[0]
    )
    rows = [("AAA", "AAA", {"session_id": "nyse"}, None), ("ZZZ", "ZZZ", {}, None)]
    out = cu.corpus_universe(_cursor_conn((3, 1, date(2020, 3, 31)), rows))
    assert out == ["AAA", "ZZZ"] and len(seen) == 2
