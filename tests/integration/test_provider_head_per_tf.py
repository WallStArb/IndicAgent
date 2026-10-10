"""Live-DB proof of the per-TF provider head write (phase 190 plan 03, contract point 5).

record_head_per_tf is the migration 465 shape and is NOT the live path until the 190-06
cutover applies 465 and flips the write. This test applies 465's provider_head re-key inside
one force-rolled-back transaction (the 190-02 post-flip pattern), proves the upsert writes
distinct per-timeframe rows under the new PK, and asserts the live PK is untouched. Runs on
indicagent_test; a synthetic symbol, so no real series is touched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from scripts.infrastructure.backfill import _empty_history as empty_history
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration


class _ForceRollback(Exception):
    pass


class _NoCommit:
    """Forwards every call to the live connection but swallows commit(): the module's own
    commit must not end the test's transaction, which is rolled back on purpose."""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        pass


@pytest.fixture()
def live():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    symbol = f"ZZ190{uuid.uuid4().hex[:10]}"
    try:
        yield conn, symbol
    finally:
        conn.execute("DELETE FROM ohlcv_provider_head WHERE symbol = %s", (symbol,))
        conn.close()


def test_record_head_per_tf_upserts_distinct_timeframe_rows(live):
    conn, symbol = live
    head_ts = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    with pytest.raises(_ForceRollback):
        with conn.transaction():  # always rolled back: the 465 shape never outlives the test
            conn.execute("ALTER TABLE ohlcv_provider_head DROP CONSTRAINT ohlcv_provider_head_pkey")
            conn.execute(
                "ALTER TABLE ohlcv_provider_head ADD PRIMARY KEY (symbol, provider, timeframe)"
            )
            shim = _NoCommit(conn)
            empty_history.record_head_per_tf(shim, symbol, "ibkr", "5m", head_ts)
            empty_history.record_head_per_tf(shim, symbol, "ibkr", "1d", head_ts)
            # the second write to the same key updates, never duplicates
            empty_history.record_head_per_tf(shim, symbol, "ibkr", "5m", head_ts)
            rows = conn.execute(
                "SELECT timeframe, count(*) FROM ohlcv_provider_head "
                "WHERE symbol = %s AND provider = 'ibkr' GROUP BY timeframe ORDER BY timeframe",
                (symbol,),
            ).fetchall()
            assert rows == [("1d", 1), ("5m", 1)]
            raise _ForceRollback
    assert (
        conn.execute(
            "SELECT count(*) FROM ohlcv_provider_head WHERE symbol = %s", (symbol,)
        ).fetchone()[0]
        == 0
    )  # rolled back: nothing leaked past the transaction
    assert (
        conn.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'ohlcv_provider_head'::regclass "
            "AND contype = 'p'"
        ).fetchone()[0]
        == "ohlcv_provider_head_pkey"
    )  # the live PK is untouched
