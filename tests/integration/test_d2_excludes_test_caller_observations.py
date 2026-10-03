"""Integration: D2's D1 reads never see observations appended by a test caller.

D1 is append-only, so a fixture row a test appends on a real symbol and date cannot be
removed, and bar_derivation takes the latest observation per bar. Runs against the
replayed indicagent_test DB; the rows it appends stay there until the next session
rebuild. Dates are 1999 so no other test's SPY rows share them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from services.bar_derivation import (
    _SELECT_DAILY_CHANGED_SINCE_SQL,
    _SELECT_DAILY_OBSERVATIONS_SQL,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_SYMBOL = "SPY"
_BAR_DATE = datetime(1999, 1, 4, tzinfo=UTC).date()

_INSERT_REQUEST = (
    "INSERT INTO ohlcv_request (request_id, fetch_run_id, symbol, timeframe, source, route, "
    "what_to_show, window_end, outcome, n_bars, caller, requested_at, answered_at) "
    "VALUES ($1, $2, $3, '1d', 'ibkr', 'SMART', 'TRADES', $4, 'bars', 1, $5, $4, $4)"
)
_INSERT_OBSERVATION = (
    "INSERT INTO ohlcv_observation (request_id, symbol, timeframe, bar_date, open, high, low, "
    "close, volume, source, route, what_to_show, fetched_at) "
    "VALUES ($1, $2, '1d', $3, $4, $4, $4, $4, 1000, 'ibkr', 'SMART', 'TRADES', $5)"
)


async def _append(conn: asyncpg.Connection, caller: str, price: float, at: datetime) -> str:
    request_id = uuid.uuid4()
    await conn.execute(_INSERT_REQUEST, request_id, uuid.uuid4(), _SYMBOL, at, caller)
    await conn.execute(_INSERT_OBSERVATION, request_id, _SYMBOL, _BAR_DATE, price, at)
    return str(request_id)


async def test_a_later_test_caller_observation_never_wins_a_bar():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        real_id = await _append(
            conn, "historical-pipeline", 472.65, datetime(2026, 9, 30, tzinfo=UTC)
        )
        await _append(conn, "test-d2-exclusion", 100.5, datetime(2026, 10, 3, tzinfo=UTC))

        rows = await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, _SYMBOL)
        at_date = [r for r in rows if r["bar_date"] == _BAR_DATE]
        assert [r["request_id"] for r in at_date] == [real_id]
        assert at_date[0]["close"] == 472.65
    finally:
        await conn.close()


async def test_a_test_caller_answer_does_not_make_a_symbol_due():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        before = await conn.fetchrow(_SELECT_DAILY_CHANGED_SINCE_SQL, _SYMBOL)
        await _append(conn, "test-d2-exclusion", 1.0, datetime(2099, 1, 1, tzinfo=UTC))
        after = await conn.fetchrow(_SELECT_DAILY_CHANGED_SINCE_SQL, _SYMBOL)
        assert dict(after) == dict(before)
    finally:
        await conn.close()
