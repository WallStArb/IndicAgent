"""Integration: D3 and D4 run on D1 for 1d (plan 185-19).

Runs against the production database (not indicagent_test) because the point is the live
ohlcv_empty_history rows and the live venue state. Strictly read-only: SELECTs only.
"""

from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill import _empty_history as eh

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_PROVIDER = "ibkr"
_SLACK = timedelta(days=2)

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


def test_every_1d_empty_history_row_is_backed_by_confirmed_spans(conn):
    rows = conn.execute(
        "SELECT symbol, empty_through, verified_from FROM ohlcv_empty_history "
        "WHERE timeframe = '1d' AND provider = %s",
        (_PROVIDER,),
    ).fetchall()
    unbacked = [
        symbol
        for symbol, empty_through, verified_from in rows
        if not any(
            start - _SLACK <= verified_from and end + _SLACK >= empty_through
            for start, end in eh.confirmed_empty_spans(conn, symbol, "1d")
        )
    ]
    assert (
        not unbacked
    ), f"{len(unbacked)} empty-history rows no recorded answer backs: {unbacked[:10]}"


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
