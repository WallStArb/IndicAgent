"""Integration: D3 and D4 run on D1 for 1d and 5m (plans 185-19 and 185-20).

Runs against the production database (not indicagent_test) because the point is the live
ohlcv_empty_history rows and the live venue state. Strictly read-only: SELECTs only.
"""

from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill import _empty_history as eh
from scripts.ops.bars import ops_intraday_venue_recovery as recovery

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_PROVIDER = "ibkr"
_SLACK = timedelta(days=2)
# A pipeline started before plan 185-19 landed writes a 1d row from its in-memory walk before it
# flushes D1 at the end of the symbol; rows younger than this are judged on a later run.
_IN_FLIGHT = timedelta(minutes=30)

# Stored ibkr_venue 1d rows in market_data_ohlcv before plan 185-19 ran. The retired
# store_bars path never wrote any (the switch was false throughout).
_IBKR_VENUE_1D_BASELINE = 0


@pytest.fixture
def conn():
    connection = psycopg.connect(_LIVE_DB_URL)
    connection.execute("SET default_transaction_read_only = on")
    try:
        yield connection
    finally:
        connection.close()


def _venue_gate(conn) -> bool:
    row = conn.execute(
        "SELECT config_value FROM config_state WHERE config_key = 'infra.bar_derivation.venue_bars_1d'"
    ).fetchone()
    return row is not None and row[0] == "true"


def _unbacked(conn, timeframe: str) -> list[str]:
    rows = conn.execute(
        "SELECT symbol, empty_through, verified_from FROM ohlcv_empty_history "
        "WHERE timeframe = %s AND provider = %s AND verified_at < now() - %s",
        (timeframe, _PROVIDER, _IN_FLIGHT),
    ).fetchall()
    return [
        symbol
        for symbol, empty_through, verified_from in rows
        if not any(
            start - _SLACK <= verified_from and end + _SLACK >= empty_through
            for start, end in eh.confirmed_empty_spans(conn, symbol, timeframe)
        )
    ]


@pytest.mark.parametrize("timeframe", ["1d"])
def test_every_empty_history_row_of_a_venue_fallback_timeframe_is_backed(conn, timeframe):
    unbacked = _unbacked(conn, timeframe)
    assert (
        not unbacked
    ), f"{len(unbacked)} {timeframe} rows no recorded answer backs: {unbacked[:10]}"


# 5m, 15m and 1h are not asserted: venue fallback is 1d-only (migration 437: a verify-only 5m walk
# downloads and discards years of venue bars), so no recorded answer can back an intraday row, and
# the intraday rows that remain are SMART-only records. For 15m and 1h: the grid is derived from 5m, so a false empty there cannot
# reach a feature, and the fetch walk still writes those rows from SMART's answer alone.
# reconcile_empty_history supports them (they inherit 5m's confirmation) for the day the
# walk stops writing them.


def test_venue_bars_never_became_canonical_while_the_gate_is_false(conn):
    if _venue_gate(conn):
        pytest.fail(
            "infra.bar_derivation.venue_bars_1d is true: add the moved-name seam and "
            "volume checks (ibkr_venue rows before the SMART head, NULL venue volume in "
            "the tradeable view, close change across the move within 5x the median "
            "absolute daily log change or a flag) before relying on venue bars"
        )
    stored = conn.execute(
        "SELECT count(*) FROM market_data_ohlcv WHERE timeframe = '1d' AND source = 'ibkr_venue'"
    ).fetchone()[0]
    assert stored == _IBKR_VENUE_1D_BASELINE
    leaked = conn.execute(
        "SELECT count(*) FROM market_data_ohlcv_tradeable "
        "WHERE source = 'ibkr_venue' AND volume IS NOT NULL"
    ).fetchone()[0]
    assert leaked == 0


def test_no_intraday_venue_bars_are_stored_before_the_recovery_unlocks(conn):
    stored = conn.execute(
        "SELECT count(*) FROM market_data_ohlcv "
        "WHERE timeframe IN ('5m', '15m', '1h') AND source = 'ibkr_venue'"
    ).fetchone()[0]
    assert stored == 0


def test_intraday_recovery_refuses_while_its_locks_are_closed(conn):
    apr = recovery._load_apr(conn)
    if recovery._is_true(apr.get(recovery._KEY_UNLOCKED)):
        pytest.skip("intraday recovery is unlocked; the refusal test no longer applies")
    refusals = recovery.recovery_refusals(conn, apr, [])
    assert any("rebuild" in reason for reason in refusals)
    assert any("verdict" in reason for reason in refusals)
