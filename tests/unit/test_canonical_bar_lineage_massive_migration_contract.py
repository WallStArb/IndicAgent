"""Migration 588 contract: canonical_bar_lineage resolves Massive canonical 1d bars (todo 600/608).

The view's exact SELECT text from the migration runs against TEMP tables shadowing the real names
(pg_temp is searched first) inside a transaction the fixture always rolls back: no live row is
read or written. Skipped when the local database is unreachable (CI); the text contract runs
everywhere.
"""

from __future__ import annotations

import functools
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import UUID

import asyncpg
import pytest

from tests.unit._migration_catalog import REPO_ROOT

_PATH = REPO_ROOT / "production" / "migrations" / "588_canonical_bar_lineage_massive.sql"
_SQL = _PATH.read_text()
_FLAT = " ".join(_SQL.split())
_VIEW = _SQL[
    _SQL.index("CREATE OR REPLACE VIEW canonical_bar_lineage AS") : _SQL.index("COMMENT ON VIEW")
]
_SELECT = _VIEW.split("AS", 1)[1].rstrip().rstrip(";")
_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def test_the_view_maps_massive_and_keeps_every_earlier_pair():
    for pair in (
        "('tradier', 'consolidated', 'tradier', 'consolidated')",
        "('ibkr', 'named', 'ibkr', 'smart_trades')",
        "('ibkr', 'fallback', 'ibkr', 'smart_trades')",
        "('alpaca', 'sip_rth', 'alpaca', 'sip_rth')",
        "('massive', 'sip_flat_adj', 'massive', 'sip_flat')",
    ):
        assert pair in _FLAT
    assert "THEN NOT (c.inferred_by = 'calendar_audit' AND c.detail ? 'rows_file')" in _FLAT
    assert "split_factor_product(c.factor ORDER BY c.effective_date)" in _FLAT
    assert _FLAT.startswith("-- 588:") and "BEGIN;" in _FLAT and _FLAT.endswith("COMMIT;")


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    import psycopg

    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


_SHADOW_DDL = """
CREATE TEMP TABLE market_data_ohlcv (
    symbol text, timeframe text, "timestamp" timestamptz, open float8, high float8, low float8,
    close float8, volume bigint, vendor text, kind text);
CREATE TEMP TABLE corporate_action_current (
    symbol text, action_type text, effective_date date, factor float8, inferred_by text,
    detail jsonb);
CREATE TEMP TABLE ohlcv_raw (
    symbol text, timeframe text, "timestamp" timestamptz, vendor text, kind text, open float8,
    high float8, low float8, close float8, volume bigint, request_id uuid, load_id uuid);
CREATE TEMP TABLE ohlcv_request (request_id uuid, caller text);
CREATE TEMP TABLE ohlcv_load (load_id uuid, caller text);
CREATE TEMP TABLE bar_content_digest (
    symbol text, timeframe text, range_start timestamptz, range_end timestamptz,
    rule_version text, batch_id uuid, computed_at timestamptz);
"""
_REQ = UUID("00000000-0000-0000-0000-0000000000a1")
_LOAD = UUID("00000000-0000-0000-0000-0000000000b1")
_OLD = datetime(2024, 6, 7, tzinfo=UTC)  # canonical stamps 00:00 UTC
_SESSION_NY = datetime(2024, 6, 7, 4, 0, tzinfo=UTC)  # Massive window_start: midnight New York


@pytest.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    if not _db_reachable():
        pytest.skip("local PostgreSQL not reachable")
    connection = await asyncpg.connect(_LIVE_DB_DSN)
    txn = connection.transaction()
    await txn.start()
    try:
        await connection.execute(_SHADOW_DDL)
        await connection.execute("INSERT INTO ohlcv_load VALUES ($1, 'massive-1d-load')", _LOAD)
        # NVDA-like: raw 1205 the session before the 10:1, canonical 120.5 after the rescale.
        await connection.execute(
            "INSERT INTO ohlcv_raw VALUES ('NVDA', '1d', $1, 'massive', 'sip_flat',"
            " 1200, 1210, 1190, 1205, 1000, $2, $3)",
            _SESSION_NY,
            _REQ,
            _LOAD,
        )
        await connection.execute(
            "INSERT INTO corporate_action_current VALUES"
            " ('NVDA', 'split', DATE '2024-06-07', 10.0, 'massive_reference', '{}')"
        )
        yield connection
    finally:
        await txn.rollback()
        await connection.close()


async def _lineage(conn: asyncpg.Connection, close: float, volume: int) -> list | None:
    await conn.execute("DELETE FROM market_data_ohlcv")
    await conn.execute(
        "INSERT INTO market_data_ohlcv VALUES ('NVDA', '1d', $1, 120, 121, 119, $2, $3,"
        " 'massive', 'sip_flat_adj')",
        _OLD,
        close,
        volume,
    )
    return await conn.fetchval(f"SELECT request_ids FROM ({_SELECT}) v")


pytestmark = pytest.mark.live_db


async def test_a_massive_bar_rescaled_by_the_market_split_has_its_lineage(conn):
    assert await _lineage(conn, 120.5, 10000) == [_REQ]
    # A bar the rule did not produce (unscaled close) has none: the equality is exact.
    assert await _lineage(conn, 1205.0, 1000) is None


async def test_an_incumbent_route_correction_never_enters_the_massive_product(conn):
    # A todo 592 operator row dated after the bar: were it applied, the expected close would be
    # 120.5 / 0.5 and the true row would read lineage_missing.
    await conn.execute(
        "INSERT INTO corporate_action_current VALUES ('NVDA', 'reverse_split', DATE"
        " '2024-06-10', 0.5, 'calendar_audit', '{\"rows_file\": \"x.csv\","
        ' "unadjusted_routes": [{"vendor": "ibkr", "kind": "smart_trades"}]}\')'
    )
    assert await _lineage(conn, 120.5, 10000) == [_REQ]


async def test_a_calendar_split_confirmed_by_the_calendar_is_a_market_split(conn):
    await conn.execute("DELETE FROM corporate_action_current")
    await conn.execute(
        "INSERT INTO corporate_action_current VALUES ('NVDA', 'split', $1, 10.0,"
        ' \'calendar_audit\', \'{"unadjusted_routes": [{"vendor": "ibkr",'
        ' "kind": "smart_trades"}]}\')',
        date(2024, 6, 7),
    )
    assert await _lineage(conn, 120.5, 10000) == [_REQ]
