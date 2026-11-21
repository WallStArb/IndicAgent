"""SecurityTypeWriter on synthetic inputs (no database)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from services import security_type_writer as stw
from src.intelligence.security_type import TYPE_RULE_ID

D1, D2 = date(2008, 6, 30), date(2016, 9, 30)
SPAN = {"first_list": "2008-06-30", "last_list": "2016-09-30"}


def _pages(as_of: date) -> list[dict]:
    base = {"page": 1, "http_status": 200, "status": "OK", "next_url": None}
    return [
        {**base, "request_key": f"{as_of.isoformat()}@{kind}"} for kind in ("active", "inactive")
    ]


class _Conn:
    def __init__(self, *, labels, instruments, dates=(D1, D2), stored=(), bad_dates=()):
        self.labels, self.instruments = labels, set(instruments)
        self.dates, self.stored, self.bad_dates = list(dates), list(stored), set(bad_dates)
        self.executemany = AsyncMock()
        self.label_reads: list[date] = []

    async def fetch(self, sql, *args):
        if sql == stw._LIST_DATES_SQL:
            return [{"as_of": d} for d in self.dates]
        if sql == stw._SNAPSHOT_PAGES_SQL:
            pages = _pages(args[0])
            return pages[:1] if args[0] in self.bad_dates else pages
        if sql == stw._LABELS_SQL:
            self.label_reads.append(args[0])
            return [{"symbol": s, "label": t} for s, t in self.labels.get(args[0], [])]
        if sql == stw._INSTRUMENTS_SQL:
            return [{"symbol": s} for s in self.instruments]
        if sql == stw._STORED_SQL:
            return self.stored
        raise AssertionError(sql)


def _writer():
    return stw.SecurityTypeWriter("dsn", apply=False)


def _records(conn):
    return conn.executemany.call_args.args[1]


async def test_one_row_per_typed_security_with_counts_and_dates_as_evidence():
    conn = _Conn(
        labels={D1: [("AAA", "CS"), ("BBB", "ETF")], D2: [("AAA", "CS"), ("BBB", "INDEX")]},
        instruments=["AAA", "BBB", "NOLABEL"],
    )
    assert await _writer()._build_and_write(conn) is True
    assert _records(conn) == [
        ("AAA", TYPE_RULE_ID, "CS", False, {"labels": {"CS": 2}, **SPAN}, "pit_snapshots"),
        (
            "BBB",
            TYPE_RULE_ID,
            "ETF",
            False,
            {"labels": {"ETF": 1, "INDEX": 1}, **SPAN},
            "pit_snapshots",
        ),
    ]  # NOLABEL is untyped: no row


async def test_a_label_missing_on_a_list_does_not_untype_the_security():
    conn = _Conn(labels={D1: [("AAA", "CS")], D2: []}, instruments=["AAA"])
    await _writer()._build_and_write(conn)
    assert [r[0] for r in _records(conn)] == ["AAA"]


async def test_the_rows_do_not_depend_on_the_order_the_database_returns_them():
    rows = [("ZZZ", "CS"), ("AAA", "PFD"), ("AAA", "CS")]
    one = _Conn(labels={D1: rows}, instruments=["AAA", "ZZZ"])
    two = _Conn(labels={D1: list(reversed(rows))}, instruments=["AAA", "ZZZ"])
    await _writer()._build_and_write(one)
    await _writer()._build_and_write(two)
    assert _records(one) == _records(two)
    assert _records(one)[0][2:4] == ("PFD", True)


async def test_an_incomplete_capture_fails_loudly_and_writes_nothing():
    conn = _Conn(labels={D1: [("AAA", "CS")]}, instruments=["AAA"], bad_dates=[D2])
    with pytest.raises(RuntimeError, match="is not captured|pages"):
        await _writer()._build_and_write(conn)
    conn.executemany.assert_not_called()


async def test_a_typed_symbol_without_an_instrument_fails_loudly():
    conn = _Conn(labels={D1: [("AAA", "CS"), ("GHOST", "CS")]}, instruments=["AAA"])
    with pytest.raises(RuntimeError, match=r"no instruments row, first \['GHOST'\]"):
        await _writer()._build_and_write(conn)
    conn.executemany.assert_not_called()


async def test_no_captured_list_fails_loudly():
    with pytest.raises(RuntimeError, match="no pit_snapshots list"):
        await _writer()._build_and_write(_Conn(labels={}, instruments=[], dates=[]))


def _stored(symbol, kind, conflict, labels):
    return {
        "symbol": symbol,
        "security_type": kind,
        "class_conflict": conflict,
        "evidence": {"labels": labels, "first_list": D1.isoformat(), "last_list": D1.isoformat()},
    }


async def test_an_existing_build_that_the_inputs_still_give_writes_nothing():
    conn = _Conn(
        labels={D1: [("AAA", "CS")]},
        instruments=["AAA"],
        dates=(D1,),
        stored=[_stored("AAA", "CS", False, {"CS": 1})],
    )
    assert await _writer()._build_and_write(conn) is False
    conn.executemany.assert_not_called()


async def test_the_comparison_with_the_stored_rows_ignores_row_order():
    conn = _Conn(
        labels={D1: [("BRK.B", "CS"), ("BRKA", "CS")]},
        instruments=["BRK.B", "BRKA"],
        dates=(D1,),
        stored=[_stored("BRKA", "CS", False, {"CS": 1}), _stored("BRK.B", "CS", False, {"CS": 1})],
    )
    assert await _writer()._build_and_write(conn) is False


async def test_an_existing_build_the_inputs_no_longer_give_raises():
    conn = _Conn(
        labels={D1: [("AAA", "CS")]},
        instruments=["AAA"],
        dates=(D1,),
        stored=[_stored("AAA", "ETF", False, {"ETF": 1})],
    )
    with pytest.raises(RuntimeError, match="no longer matches"):
        await _writer()._build_and_write(conn)
    conn.executemany.assert_not_called()


async def test_a_list_after_L_refuses_the_build():
    conn = _Conn(labels={}, instruments=[], dates=(D1, date(2026, 11, 30)))
    with pytest.raises(RuntimeError, match="after L"):
        await _writer()._build_and_write(conn)
    conn.executemany.assert_not_called()


async def test_labels_are_read_one_list_date_at_a_time():
    conn = _Conn(labels={D1: [("AAA", "CS")]}, instruments=["AAA"])
    await _writer()._build_and_write(conn)
    assert conn.label_reads == [D1, D2]
