"""Plan 185-51 (todo 515): a held name, defined once in bar_hold (migration 461).

A name is held for a timeframe while bar_hold_current has a row for it. services/bar_hold.py is
the one writer (record_hold, release_hold, under bar_derivation_writer) and the one read the
fetcher's overlap judge, the daily stage and D7 share. Against a fake connection.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime

import pytest

from services import bar_hold as bh

_AT = datetime(2026, 10, 8, 15, 13, tzinfo=UTC)


def _hold_row(symbol="CTVA", factor=39 / 7, **over):
    row = {
        "hold_id": "aaaaaaaa-0000-0000-0000-000000000001",
        "symbol": symbol,
        "timeframe": "1d",
        "reason": "unclassified_rescale",
        "factor": factor,
        "first_affected_date": date(2019, 5, 24),
        "last_affected_date": date(2026, 9, 30),
        "action_id": None,
        "detail": {"vendor_ratios": {"SMART": {"median_ratio": 5.5711}}},
        "recorded_by": "ops_split_detect",
        "recorded_at": _AT,
    }
    row.update(over)
    return row


class FakeConn:
    def __init__(self, existing=(), ratios=()):
        self.existing = list(existing)
        self.ratios = list(ratios)
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        flat = " ".join(sql.split())
        self.fetched.append((flat, args))
        if "ohlcv_observation" in flat:
            return self.ratios
        assert "bar_hold_current" in flat, flat
        if "symbol = $1" in flat:
            return [r for r in self.existing if r["symbol"] == args[0]]
        return [r for r in self.existing if r["timeframe"] == args[0]]

    async def fetchrow(self, sql, *args):
        flat = " ".join(sql.split())
        self.fetched.append((flat, args))
        return next((r for r in self.existing if r["hold_id"] == args[0]), None)


def _record(conn, **over):
    kw = {
        "symbol": "CTVA",
        "timeframe": "1d",
        "reason": bh.REASON_UNCLASSIFIED_RESCALE,
        "factor": 5.5714,
        "first_affected_date": date(2026, 9, 3),
        "last_affected_date": date(2026, 9, 30),
        "detail": {"vendor_ratios": {"SMART": {"median_ratio": 5.5714, "n_dates": 20}}},
        "recorded_by": "ibkr-history-fetcher",
        "rel_tol": 0.002,
    }
    kw.update(over)
    return asyncio.run(bh.record_hold(conn, **kw))


def test_a_new_hold_is_inserted_under_the_writer_role():
    conn = FakeConn()
    hold_id = _record(conn)
    assert hold_id
    role, insert = conn.executed
    assert role[0] == "SET LOCAL ROLE bar_derivation_writer"
    sql, args = insert
    assert sql.startswith("INSERT INTO bar_hold")
    assert args[0] == hold_id and args[1:4] == ("CTVA", "1d", "unclassified_rescale")
    assert args[4] == 5.5714 and args[5:7] == (date(2026, 9, 3), date(2026, 9, 30))
    assert json.loads(args[8])["vendor_ratios"]["SMART"]["n_dates"] == 20
    assert "$9::text::jsonb" in sql  # one JSON encoding whatever codecs the connection has


def test_the_same_rescale_is_never_held_twice():
    """Idempotent per symbol and factor: the overlap judge may see the same rescale again."""
    conn = FakeConn(existing=[_hold_row(factor=5.5711)])
    assert _record(conn, factor=5.5714) is None
    assert not [s for s, _ in conn.executed if s.startswith("INSERT")]


def test_a_different_factor_on_a_held_name_is_a_second_hold():
    conn = FakeConn(existing=[_hold_row(factor=5.5711)])
    assert _record(conn, factor=2.37)
    assert [s for s, _ in conn.executed if s.startswith("INSERT")]


def test_a_hold_needs_a_known_reason_and_a_positive_factor():
    with pytest.raises(ValueError, match="reason"):
        _record(FakeConn(), reason="release")
    with pytest.raises(ValueError, match="factor"):
        _record(FakeConn(), factor=0.0)


def test_held_reads_the_current_view_per_timeframe_and_states_the_cause():
    conn = FakeConn(existing=[_hold_row(), _hold_row(symbol="XYZ", factor=2.37)])
    held = asyncio.run(bh.held(conn, "1d"))
    assert sorted(held) == ["CTVA", "XYZ"]
    sql, args = conn.fetched[0]
    assert "FROM bar_hold_current" in sql and "timeframe = $1" in sql and args == ("1d",)
    (hold,) = held["CTVA"]
    assert hold.cause() == (
        "unclassified_rescale factor 5.5714 over 2019-05-24..2026-09-30, held since 2026-10-08"
    )


def test_release_inserts_a_release_row_for_an_open_hold():
    conn = FakeConn(existing=[_hold_row()])
    release_id = asyncio.run(
        bh.release_hold(
            conn,
            hold_id="aaaaaaaa-0000-0000-0000-000000000001",
            why="spin_off treatment landed",
            recorded_by="ops_split_detect",
        )
    )
    sql, args = [e for e in conn.executed if e[0].startswith("INSERT")][0]
    assert args[0] == release_id and args[1:4] == ("CTVA", "1d", "release")
    assert args[-1] == "aaaaaaaa-0000-0000-0000-000000000001"  # releases
    assert json.loads(args[8]) == {"why": "spin_off treatment landed"}


def test_release_of_an_unknown_or_released_hold_raises():
    with pytest.raises(LookupError, match="no open hold"):
        asyncio.run(bh.release_hold(FakeConn(), hold_id="x", why="w", recorded_by="r"))


def test_vendor_ratios_compare_each_routes_latest_answer_with_the_canonical_bar():
    conn = FakeConn(
        ratios=[
            {
                "route": "SMART",
                "n_dates": 1848,
                "median_ratio": 5.5711,
                "first_date": date(2019, 5, 24),
                "last_date": date(2026, 9, 30),
            },
            {
                "route": "TRADIER",
                "n_dates": 1848,
                "median_ratio": 6.665,
                "first_date": date(2019, 5, 24),
                "last_date": date(2026, 9, 30),
            },
        ]
    )
    ratios = asyncio.run(
        bh.vendor_rescale_ratios(conn, "CTVA", None, date(2026, 9, 30), rel_tol=0.002)
    )
    assert ratios["SMART"]["median_ratio"] == 5.5711 and ratios["TRADIER"]["n_dates"] == 1848
    assert ratios["TRADIER"]["first_date"] == "2019-05-24"
    sql, args = conn.fetched[0]
    assert "market_data_ohlcv_tradeable" in sql and "q.caller NOT LIKE 'test-%'" in sql
    assert args == ("CTVA", None, date(2026, 9, 30), 0.002)
