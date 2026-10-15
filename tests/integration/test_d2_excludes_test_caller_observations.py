"""Integration: the daily stage's raw 1d read never takes a value a test caller served.

Raw is last-wins, so a fixture value a test serves on a real symbol and date replaces the real
one in ohlcv_raw; the read excludes it through its request_id's caller (and a row with no
request, a legacy migrated row, is no test row). Runs against the replayed indicagent_test DB
inside a rolled-back transaction. Dates are 1999 so no other test's SPY rows share them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from services.bar_derivation import (
    _RAW_DAILY_KINDS,
    _RAW_DAILY_VENDORS,
    _SELECT_DAILY_CHANGED_SINCE_SQL,
    _SELECT_DAILY_RAW_SQL,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_SYMBOL = "SPY"
_DAY = datetime(1999, 1, 4, tzinfo=UTC)
_DAY2 = datetime(1999, 1, 5, tzinfo=UTC)

_INSERT_REQUEST = (
    "INSERT INTO ohlcv_request (request_id, fetch_run_id, symbol, timeframe, source, route, "
    "what_to_show, window_end, outcome, n_bars, caller, requested_at, answered_at) "
    "VALUES ($1, $2, $3, '1d', 'ibkr', 'SMART', 'TRADES', $4, 'bars', 1, $5, $4, $4)"
)
_UPSERT_RAW = (
    'INSERT INTO ohlcv_raw ("timestamp", symbol, timeframe, vendor, kind, open, high, low, '
    "close, volume, served_at, request_id) "
    "VALUES ($1, $2, '1d', 'ibkr', 'smart_trades', $3, $3, $3, $3, 1000, $4, $5) "
    'ON CONFLICT ("timestamp", symbol, timeframe, vendor, kind) DO UPDATE SET '
    "close = EXCLUDED.close, open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, "
    "served_at = EXCLUDED.served_at, request_id = EXCLUDED.request_id"
)


async def _serve(conn, day: datetime, caller: str | None, price: float, at: datetime) -> None:
    request_id = None
    if caller is not None:
        request_id = uuid.uuid4()
        await conn.execute(_INSERT_REQUEST, request_id, uuid.uuid4(), _SYMBOL, at, caller)
    await conn.execute(_UPSERT_RAW, day, _SYMBOL, price, at, request_id)


async def _connect() -> asyncpg.Connection:
    try:
        conn = await asyncpg.connect(_TEST_DB_URL)
    except Exception as error:  # reachability probe
        pytest.skip(f"indicagent_test not reachable: {error}")
    if not await conn.fetchval("SELECT to_regclass('ohlcv_raw') IS NOT NULL"):
        await conn.close()
        pytest.skip("indicagent_test has no ohlcv_raw")
    return conn


async def test_a_test_caller_value_is_never_read_and_a_null_request_row_is():
    conn = await _connect()
    txn = conn.transaction()
    await txn.start()
    try:
        await _serve(conn, _DAY, "test-d2-exclusion", 100.5, datetime(2026, 10, 3, tzinfo=UTC))
        await _serve(conn, _DAY2, None, 472.65, datetime(2026, 9, 30, tzinfo=UTC))
        rows = await conn.fetch(
            _SELECT_DAILY_RAW_SQL, _SYMBOL, _RAW_DAILY_VENDORS, _RAW_DAILY_KINDS
        )
        by_day = {r["bar_date"]: r for r in rows}
        assert _DAY.date() not in by_day
        assert (
            by_day[_DAY2.date()]["close"] == 472.65 and by_day[_DAY2.date()]["request_id"] is None
        )
    finally:
        await txn.rollback()
        await conn.close()


async def test_a_test_caller_serve_does_not_make_a_symbol_due_by_itself():
    conn = await _connect()
    txn = conn.transaction()
    await txn.start()
    try:
        await _serve(conn, _DAY, "test-d2-exclusion", 1.0, datetime(2099, 1, 1, tzinfo=UTC))
        probe = await conn.fetchrow(
            _SELECT_DAILY_CHANGED_SINCE_SQL, _SYMBOL, _RAW_DAILY_VENDORS, _RAW_DAILY_KINDS
        )
        # has_obs ignores the test row; obs_since sees any served value change (a test serve on
        # a live symbol re-derives it, and the re-derivation reads no test value).
        assert probe["obs_since"]
        rows = await conn.fetch(
            _SELECT_DAILY_RAW_SQL, _SYMBOL, _RAW_DAILY_VENDORS, _RAW_DAILY_KINDS
        )
        assert _DAY.date() not in {r["bar_date"] for r in rows}
    finally:
        await txn.rollback()
        await conn.close()
