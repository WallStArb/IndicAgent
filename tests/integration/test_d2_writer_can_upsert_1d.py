"""Integration: bar_derivation_writer can run the daily stage's 1d upsert (migration 435).

Migration 383 granted the role SELECT, INSERT, DELETE on market_data_ohlcv; the daily
stage's INSERT ... ON CONFLICT DO UPDATE also needs UPDATE, and the first pilot apply
failed every symbol with "permission denied" while every unit test passed, because
unit tests cannot see grants. Runs the real _UPSERT_1D_SQL under the real role against
the replayed indicagent_test DB, twice, so the second statement takes the conflict arm.
"""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from services.bar_derivation import _UPSERT_1D_SQL

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_TS = datetime(1999, 1, 4, tzinfo=UTC)


async def test_the_writer_role_insert_then_conflict_update_of_a_1d_bar():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE bar_derivation_writer")
            for close in (10.5, 11.5):
                await conn.execute(
                    _UPSERT_1D_SQL,
                    _TS,
                    "SPY",
                    "1d",
                    10.0,
                    12.0,
                    9.0,
                    close,
                    1000,
                    "ibkr_named",
                    "SPY",
                )
            row = await conn.fetchrow(
                "SELECT close, source FROM market_data_ohlcv "
                "WHERE symbol = 'SPY' AND timeframe = '1d' AND \"timestamp\" = $1",
                _TS,
            )
            assert (row["close"], row["source"]) == (11.5, "ibkr_named")
            await conn.execute("RESET ROLE")
            raise _Rollback
    except _Rollback:
        pass
    finally:
        await conn.close()


class _Rollback(Exception):
    pass
