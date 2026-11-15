"""UniverseMembershipWriter and corpus_universe on synthetic inputs (no database)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import corpus_universe as cu
from services import universe_membership_writer as w


def test_month_ends_through_are_complete_nyse_month_ends():
    ends = w.month_ends_through(date(2020, 3, 15))
    assert ends[-1] == date(2020, 2, 28)  # March is partial: no March month-end yet
    assert date(2020, 1, 31) in ends and date(2019, 12, 31) in ends
    assert w.month_ends_through(date(2020, 3, 31))[-1] == date(2020, 3, 31)
    assert w.month_ends_through(date(2003, 9, 30)) == [date(2003, 9, 30)]


def test_histories_group_by_symbol_in_order():
    rec = [
        ("A", date(2020, 1, 2), 10.0, 100.0),
        ("A", date(2020, 1, 3), 11.0, 200.0),
        ("B", date(2020, 1, 2), 5.0, 50.0),
    ]
    hist = w.histories_from_records(rec)
    assert sorted(hist) == ["A", "B"] and len(hist["A"].days) == 2
    assert hist["A"].close.tolist() == [10.0, 11.0]


class _Conn:
    """Minimal asyncpg connection double."""

    def __init__(self, ledger, snapshots):
        self.ledger, self.snapshots = ledger, snapshots
        self.executemany = AsyncMock()
        self.copy_records_to_table = AsyncMock()

    async def fetch(self, sql, *args):
        if sql == w._LEDGER_SQL:
            return self.ledger
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if sql == w._SNAPSHOT_PRESENT_SQL:
            return self.snapshots.get(args[0], 0)
        raise AssertionError(sql)


async def test_missing_snapshot_fails_loudly_and_writes_nothing():
    writer = w.UniverseMembershipWriter("dsn", date(2003, 9, 30))
    conn = _Conn([], {})
    with pytest.raises(RuntimeError, match="no pit_snapshots capture"):
        await writer._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()


async def test_foreign_rule_id_refuses_extension():
    writer = w.UniverseMembershipWriter("dsn", date(2020, 3, 31))
    conn = _Conn([{"as_of": date(2020, 1, 31), "rule_id": "other"}], {})
    with pytest.raises(RuntimeError, match="built under rule"):
        await writer._build_and_write(conn)


async def test_up_to_date_ledger_writes_nothing():
    writer = w.UniverseMembershipWriter("dsn", date(2003, 9, 30))
    conn = _Conn([{"as_of": date(2003, 9, 30), "rule_id": w.RULE_ID}], {})
    assert await writer._build_and_write(conn) is False


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


def _weekdays(start: date, n: int) -> list[date]:
    from datetime import timedelta

    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _build_conn(last_day: date):
    days = [d for d in _weekdays(date(2003, 9, 10), 90) if d <= last_day]
    ends = w.month_ends_through(date(2003, 12, 31))

    class Conn(_Conn):
        async def fetch(self, sql, *args):
            if sql == w._PLACED_SYMBOLS_SQL:
                return [{"symbol": s} for s in ("AAA", "PPP", "THIN")]
            if sql == w._TYPES_SQL:
                return [
                    {"symbol": "AAA", "security_type": "CS"},
                    {"symbol": "PPP", "security_type": "PFD"},
                    {"symbol": "THIN", "security_type": "CS"},
                ]
            if sql == w._BARS_SQL:
                return [
                    (s, d, 10.0, dollars / 10.0)
                    for s, dollars in (("AAA", 2e6), ("PPP", 2e6), ("THIN", 1e5))
                    for d in days
                ]
            return await super().fetch(sql, *args)

    return Conn([], {m: 1 for m in ends})


async def test_build_writes_ledger_for_empty_early_months_and_members_after():
    conn = _build_conn(date(2003, 12, 31))
    writer = w.UniverseMembershipWriter("dsn", date(2003, 12, 31))
    assert await writer._build_and_write(conn) is True
    ledger = conn.executemany.call_args.args[1]
    assert [(m, n) for m, _, n in ledger] == [
        (date(2003, 9, 30), 0),
        (date(2003, 10, 31), 0),
        (date(2003, 11, 28), 0),
        (date(2003, 12, 31), 1),
    ]
    records = conn.copy_records_to_table.call_args.kwargs["records"]
    assert [(r[0], r[1], r[2], r[6]) for r in records] == [(date(2003, 12, 31), "AAA", "CS", True)]


async def test_build_with_no_member_in_the_run_fails_loudly():
    conn = _build_conn(date(2003, 9, 30))
    writer = w.UniverseMembershipWriter("dsn", date(2003, 9, 30))
    with pytest.raises(RuntimeError, match="no member"):
        await writer._build_and_write(conn)
    conn.copy_records_to_table.assert_not_called()
    conn.executemany.assert_not_called()


def test_qualifying_member_rows_via_walk():
    from src.intelligence.universe_membership import memberships_for_security

    days = _weekdays(date(2003, 9, 10), 90)
    hist = w.histories_from_records([("AAA", d, 10.0, 2e5) for d in days])["AAA"]
    dec = date(2003, 12, 31)
    rows = memberships_for_security(hist, [dec], {dec: "CS"})
    assert [(r.symbol, r.entered) for r in rows] == [("AAA", True)]
