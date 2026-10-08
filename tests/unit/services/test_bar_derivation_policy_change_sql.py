"""The daily stage sees a closed 1d policy row (plan 185-50, todo 508).

A close changes valid_to only; migration 460 stamps it in bar_source_policy.closed_at (the
append-only trigger sets it on the one allowed closing UPDATE). The revision-ratio waiver and the
nightly --changed-only probe compare GREATEST(recorded_at, closed_at) with the symbol's own last
applied daily load, so a close after that load waives the revision limit and makes the symbol
due, and nothing else does: a closed row of another symbol, or one closed before the load, or a
legacy closed row with no stamp, never waives a real vendor revision.

Runs the exact SQL text from services/bar_derivation.py against the local PostgreSQL, with TEMP
tables shadowing the real names (pg_temp is searched first), inside a transaction that is rolled
back: no live row is read or written. The trigger test attaches the live trigger function to a
TEMP copy of bar_source_policy. Skipped when the database is unreachable (CI).
"""

from __future__ import annotations

import functools
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from services.bar_derivation import (
    _SELECT_DAILY_CHANGED_SINCE_SQL,
    _SELECT_REVISION_WAIVER_SQL,
)

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    import psycopg

    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="local PostgreSQL not reachable")

_T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
_LOAD = _T0 + timedelta(hours=4)  # the symbol's last applied daily load

_SHADOW_DDL = """
CREATE TEMP TABLE ohlcv_load (
    symbol text, timeframe text, source text, outcome text, caller text, loaded_at timestamptz,
    batch_id int);
CREATE TEMP TABLE corporate_action (symbol text, recorded_at timestamptz);
CREATE TEMP TABLE corporate_action_current (symbol text, recorded_at timestamptz);
CREATE TEMP TABLE bar_derivation_batch (
    batch_id int, stage text, status text, started_at timestamptz, finished_at timestamptz);
CREATE TEMP TABLE ohlcv_request (
    request_id int, symbol text, timeframe text, what_to_show text, outcome text, caller text,
    answered_at timestamptz);
CREATE TEMP TABLE ohlcv_observation (
    request_id int, symbol text, timeframe text, what_to_show text, route text);
CREATE TEMP TABLE bar_source_policy (
    timeframe text, symbol text, valid_to date, primary_source text,
    recorded_at timestamptz, closed_at timestamptz);
"""


@pytest.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(_LIVE_DB_DSN)
    txn = connection.transaction()
    await txn.start()
    try:
        await connection.execute(_SHADOW_DDL)
        # TEST: answered once at T0, derived and applied at _LOAD. OTHER: a second name.
        await connection.execute(
            "INSERT INTO ohlcv_request VALUES"
            " (1, 'TEST', '1d', 'TRADES', 'bars', 'fetcher', $1),"
            " (2, 'OTHER', '1d', 'TRADES', 'bars', 'fetcher', $1)",
            _T0,
        )
        await connection.execute(
            "INSERT INTO ohlcv_observation VALUES"
            " (1, 'TEST', '1d', 'TRADES', 'SMART'), (2, 'OTHER', '1d', 'TRADES', 'SMART')"
        )
        # Legacy loads with no batch: the baseline is loaded_at.
        await connection.execute(
            "INSERT INTO ohlcv_load VALUES"
            " ('TEST', '1d', 'derived', 'applied', 'bar_derivation-daily', $1, NULL),"
            " ('OTHER', '1d', 'derived', 'applied', 'bar_derivation-daily', $1, NULL)",
            _LOAD,
        )
        await connection.execute(
            "INSERT INTO bar_derivation_batch VALUES (1, 'daily', 'completed', $1, $2)",
            _LOAD - timedelta(minutes=1),
            _LOAD + timedelta(minutes=1),
        )
        # Open timeframe default and an open TEST row, both recorded long before the load.
        await connection.execute(
            "INSERT INTO bar_source_policy VALUES"
            " ('1d', NULL, NULL, 'ibkr', $1, NULL),"
            " ('1d', 'TEST', NULL, 'ibkr', $1, NULL)",
            _T0 - timedelta(days=30),
        )
        yield connection
    finally:
        await txn.rollback()
        await connection.close()


async def _close(conn: asyncpg.Connection, symbol: str, closed_at: datetime | None) -> None:
    await conn.execute(
        "INSERT INTO bar_source_policy VALUES ('1d', $1, DATE '2016-06-14', 'ibkr', $2, $3)",
        symbol,
        _T0 - timedelta(days=1),
        closed_at,
    )


async def _waived(conn: asyncpg.Connection, symbol: str = "TEST") -> bool:
    return bool(await conn.fetchval(_SELECT_REVISION_WAIVER_SQL, symbol))


async def _probe(conn: asyncpg.Connection, symbol: str = "TEST") -> asyncpg.Record:
    return await conn.fetchrow(_SELECT_DAILY_CHANGED_SINCE_SQL, symbol)


async def test_baseline_nothing_changed_since_the_last_load(conn):
    assert not await _waived(conn)
    probe = await _probe(conn)
    assert probe["has_obs"]
    assert not (probe["obs_since"] or probe["action_since"] or probe["policy_since"])


async def test_a_close_after_the_last_load_waives_and_makes_the_symbol_due(conn):
    await _close(conn, "TEST", _LOAD + timedelta(minutes=5))
    assert await _waived(conn)
    assert (await _probe(conn))["policy_since"]


async def test_a_later_subset_batch_does_not_hide_the_close_from_the_probe(conn):
    # 185-49: the three closes at 20:15 preceded a completed 38-name batch at 20:16 that never
    # touched FTV, IP or STE; the probe's baseline is the symbol's own last applied load.
    await _close(conn, "TEST", _LOAD + timedelta(minutes=5))
    await conn.execute(
        "INSERT INTO bar_derivation_batch VALUES (2, 'daily', 'completed', $1, $2)",
        _LOAD + timedelta(minutes=8),
        _LOAD + timedelta(minutes=10),
    )
    await conn.execute(
        "INSERT INTO ohlcv_load VALUES"
        " ('OTHER', '1d', 'derived', 'applied', 'bar_derivation-daily', $1, 2)",
        _LOAD + timedelta(minutes=9),
    )
    assert (await _probe(conn))["policy_since"]
    assert not (await _probe(conn, "OTHER"))["policy_since"]


async def test_a_close_of_another_symbol_does_not_waive(conn):
    await _close(conn, "OTHER", _LOAD + timedelta(minutes=5))
    assert not await _waived(conn)
    assert not (await _probe(conn))["policy_since"]


async def test_a_close_before_the_last_load_does_not_waive(conn):
    await _close(conn, "TEST", _LOAD - timedelta(minutes=5))
    assert not await _waived(conn)
    assert not (await _probe(conn))["policy_since"]


async def test_a_legacy_close_with_no_stamp_is_not_newer(conn):
    await _close(conn, "TEST", None)
    assert not await _waived(conn)
    assert not (await _probe(conn))["policy_since"]


async def test_a_default_row_closed_after_the_load_still_waives(conn):
    await conn.execute(
        "INSERT INTO bar_source_policy VALUES ('1d', NULL, DATE '1990-01-02', 'tradier', $1, $2)",
        _T0 - timedelta(days=60),
        _LOAD + timedelta(minutes=5),
    )
    assert await _waived(conn)
    assert (await _probe(conn))["policy_since"]


async def test_new_answers_after_the_symbols_own_load_are_due_past_a_later_batch(conn):
    await conn.execute(
        "INSERT INTO ohlcv_request VALUES (3, 'TEST', '1d', 'TRADES', 'bars', 'fetcher', $1)",
        _LOAD + timedelta(minutes=5),
    )
    await conn.execute(
        "INSERT INTO bar_derivation_batch VALUES (2, 'daily', 'completed', $1, $2)",
        _LOAD + timedelta(minutes=8),
        _LOAD + timedelta(minutes=10),
    )
    assert (await _probe(conn))["obs_since"]
    assert not (await _probe(conn, "OTHER"))["obs_since"]


async def test_a_close_after_the_batch_read_its_policy_but_before_the_load_waives(conn):
    # The policy is read once at run start: a close between the batch start and the symbol's
    # load row was not applied by that load.
    await conn.execute(
        "INSERT INTO bar_derivation_batch VALUES (3, 'daily', 'completed', $1, $2)",
        _LOAD + timedelta(minutes=20),
        _LOAD + timedelta(minutes=40),
    )
    await conn.execute(
        "INSERT INTO ohlcv_load VALUES"
        " ('TEST', '1d', 'derived', 'applied', 'bar_derivation-daily', $1, 3)",
        _LOAD + timedelta(minutes=30),
    )
    await _close(conn, "TEST", _LOAD + timedelta(minutes=25))
    assert await _waived(conn)
    assert (await _probe(conn))["policy_since"]


async def test_a_refused_or_restore_load_is_not_the_baseline(conn):
    await _close(conn, "TEST", _LOAD + timedelta(minutes=5))
    await conn.execute(
        "INSERT INTO ohlcv_load VALUES"
        " ('TEST', '1d', 'derived', 'refused', 'bar_derivation-daily', $1, NULL),"
        " ('TEST', '1d', 'derived', 'applied', 'bar_derivation-other', $1, NULL)",
        _LOAD + timedelta(minutes=10),
    )
    assert await _waived(conn)
    assert (await _probe(conn))["policy_since"]


async def test_a_symbol_with_no_applied_load_is_due(conn):
    await conn.execute(
        "INSERT INTO ohlcv_request VALUES (4, 'NEW', '1d', 'TRADES', 'bars', 'fetcher', $1)", _T0
    )
    await conn.execute("INSERT INTO ohlcv_observation VALUES (4, 'NEW', '1d', 'TRADES', 'SMART')")
    assert (await _probe(conn, "NEW"))["obs_since"]
    assert await _waived(conn, "NEW")


# --- the live trigger function on a TEMP copy of the table (migration 460) --------------------


@pytest.fixture
async def policy_copy() -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(_LIVE_DB_DSN)
    txn = connection.transaction()
    await txn.start()
    try:
        await connection.execute(
            "CREATE TEMP TABLE bar_source_policy"
            " (LIKE public.bar_source_policy INCLUDING DEFAULTS INCLUDING CONSTRAINTS);"
            "CREATE TRIGGER trg_copy BEFORE INSERT OR UPDATE OR DELETE ON pg_temp.bar_source_policy"
            " FOR EACH ROW EXECUTE FUNCTION public.bar_source_policy_append_only();"
        )
        yield connection
    finally:
        await txn.rollback()
        await connection.close()


_COPY_INSERT = """
INSERT INTO pg_temp.bar_source_policy
    (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, reason)
VALUES ('1d', 'TEST', DATE '2016-06-13', $1, 'observed', 'ibkr', 'test')
RETURNING policy_id
"""


async def test_the_closing_update_stamps_closed_at(policy_copy):
    policy_id = await policy_copy.fetchval(_COPY_INSERT, None)
    before = await policy_copy.fetchval("SELECT now()")
    await policy_copy.execute(
        "UPDATE pg_temp.bar_source_policy SET valid_to = DATE '2016-06-14' WHERE policy_id = $1",
        policy_id,
    )
    row = await policy_copy.fetchrow(
        "SELECT recorded_at, closed_at FROM pg_temp.bar_source_policy WHERE policy_id = $1",
        policy_id,
    )
    assert row["closed_at"] is not None and row["closed_at"] >= before
    assert row["closed_at"] >= row["recorded_at"]


async def test_an_insert_cannot_carry_closed_at(policy_copy):
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await policy_copy.execute(
            "INSERT INTO pg_temp.bar_source_policy (timeframe, symbol, valid_from, valid_to,"
            " ingress_mode, primary_source, reason, closed_at)"
            " VALUES ('1d', 'TEST', DATE '2016-06-13', DATE '2016-06-14', 'observed', 'ibkr',"
            " 'test', now())"
        )


async def test_an_inserted_closed_row_keeps_closed_at_null(policy_copy):
    policy_id = await policy_copy.fetchval(_COPY_INSERT, datetime(2016, 6, 14).date())
    assert (
        await policy_copy.fetchval(
            "SELECT closed_at FROM pg_temp.bar_source_policy WHERE policy_id = $1", policy_id
        )
        is None
    )


async def test_a_closed_row_stays_immutable_including_closed_at(policy_copy):
    policy_id = await policy_copy.fetchval(_COPY_INSERT, None)
    await policy_copy.execute(
        "UPDATE pg_temp.bar_source_policy SET valid_to = DATE '2016-06-14' WHERE policy_id = $1",
        policy_id,
    )
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await policy_copy.execute(
            "UPDATE pg_temp.bar_source_policy SET closed_at = now() + interval '1 day'"
            " WHERE policy_id = $1",
            policy_id,
        )
