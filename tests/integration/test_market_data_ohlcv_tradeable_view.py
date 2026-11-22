"""Integration: the market_data_ohlcv_tradeable view's visibility rules and column contract.

Runs on the test database with fixture rows, each test inside a transaction it rolls back. The
quarantine and column-contract tests carry the standing invariants of the deleted live-reading
checks of migration 381 and the phase 185 scrub pass (todo 656 task 1): a quarantined bar is
hidden, an informational flag hides nothing, the view admits no quarantined bar, and the column
list research reads is fixed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from tests.integration.conftest import connect

pytestmark = pytest.mark.integration

_SYMBOL = "ZZTEST"
_T0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
_COLUMNS = [
    "timestamp",
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vendor",
    "kind",
    "base",
    "price_sanity_status",
]


@pytest.fixture
def cur() -> Iterator[psycopg.Cursor]:
    with connect(autocommit=False) as conn:
        try:
            with conn.cursor() as cursor:
                yield cursor
        finally:
            conn.rollback()


def _stamp(i: int) -> datetime:
    return _T0 + timedelta(minutes=5 * i)


def _bar(cur: psycopg.Cursor, i: int, volume: int, *, kind: str = "sip_flat_adj") -> None:
    cur.execute(
        "INSERT INTO market_data_ohlcv"
        ' ("timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind)'
        " VALUES (%s, %s, '5m', 100.0, 100.5, 99.5, 100.2, %s, 'massive', %s)",
        (_stamp(i), _SYMBOL, volume, kind),
    )


def _flag(cur: psycopg.Cursor, i: int, rule: str, *, quarantine: bool, timeframe="5m") -> None:
    cur.execute(
        "INSERT INTO bar_quality_flag"
        ' (symbol, timeframe, "timestamp", rule, rule_version, quarantine)'
        " VALUES (%s, %s, %s, %s, 'test', %s)",
        (_SYMBOL, timeframe, _stamp(i), rule, quarantine),
    )


def _visible(cur: psycopg.Cursor) -> list[datetime]:
    cur.execute(
        'SELECT "timestamp" FROM market_data_ohlcv_tradeable WHERE symbol = %s ORDER BY 1',
        (_SYMBOL,),
    )
    return [row[0] for row in cur.fetchall()]


def test_view_excludes_zero_volume_bars_and_includes_real_bars(cur):
    _bar(cur, 0, 500)
    _bar(cur, 1, 0)
    _bar(cur, 2, 0)
    assert _visible(cur) == [_stamp(0)]


def test_quarantined_bar_is_hidden(cur):
    for i in range(3):
        _bar(cur, i, 500)
    _flag(cur, 1, "price_sanity", quarantine=True)
    # Two rules on one bar, one of them quarantining: the bar stays hidden.
    _flag(cur, 2, "isolated_wick", quarantine=False)
    _flag(cur, 2, "vendor_disagreement", quarantine=True)
    assert _visible(cur) == [_stamp(0)]
    cur.execute("SELECT count(*) FROM market_data_ohlcv WHERE symbol = %s", (_SYMBOL,))
    assert cur.fetchone()[0] == 3, "a flag hides a bar, it never deletes or rewrites it"
    cur.execute(
        "SELECT count(*) FROM market_data_ohlcv_tradeable t"
        ' JOIN bar_quality_flag q USING (symbol, timeframe, "timestamp")'
        " WHERE q.quarantine"
    )
    assert cur.fetchone()[0] == 0, "the view admits no quarantined bar"


def test_flagged_unquarantined_bar_is_visible(cur):
    _bar(cur, 0, 500)
    _bar(cur, 1, 500)
    _flag(cur, 0, "isolated_wick", quarantine=False)
    # A quarantine on another timeframe at the same stamp is not this bar's.
    _flag(cur, 1, "price_sanity", quarantine=True, timeframe="15m")
    assert _visible(cur) == [_stamp(0), _stamp(1)]


def test_view_column_contract(cur):
    cur.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = 'market_data_ohlcv_tradeable'"
        " ORDER BY ordinal_position"
    )
    assert [row[0] for row in cur.fetchall()] == _COLUMNS
    # Single-venue volume is not consolidated: the view nulls it for kind venue only.
    _bar(cur, 0, 500, kind="venue")
    _bar(cur, 1, 700)
    cur.execute(
        'SELECT kind, volume FROM market_data_ohlcv_tradeable WHERE symbol = %s ORDER BY "timestamp"',
        (_SYMBOL,),
    )
    assert cur.fetchall() == [("venue", None), ("sip_flat_adj", 700)]
