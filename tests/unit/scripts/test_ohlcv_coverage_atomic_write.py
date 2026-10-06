"""Live-DB proof of the three-way atomic write (phase 189 plan 01, CD-04, CD-05, CD-14).

Runs against the local PostgreSQL the way tests/unit/core/test_resource_lease.py does (the
integration suite's migrated_test_database fixture is blocked by todo 486), and skips cleanly
when no database is reachable. Real tables, real NOLOGIN roles and grants: a request row, the
archive rows and the ohlcv_coverage row either all commit or none do.

Each case uses its own synthetic symbol (ZZ189 + random hex) at the current UTC hour, so the
archive rows land in an uncompressed chunk and no real series is touched. ohlcv_request has an
FK to instruments, so the case registers the symbol as an inactive instrument first.

Cleanup: ohlcv_request (migration 380) and ohlcv_intraday_raw_archive (migration 383) are
append-only by trigger, so removing the synthetic rows needs session_replication_role = replica
for those two DELETEs, inside a transaction scoped to the test symbol. That bypass is test-only; production code never deletes a request.
"""

from __future__ import annotations

import functools
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill import _intraday_persist
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.intraday_raw_archive import insert_fetched_archive_rows
from services.ohlcv_coverage_writer import (
    CoverageDelta,
    record_fetch_outcome,
    refresh_1d_bounds,
)

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"
_N_BARS = 3


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="local PostgreSQL not reachable")


def _symbol() -> str:
    return f"ZZ189{uuid.uuid4().hex[:6].upper()}"


def _register(conn: psycopg.Connection, symbol: str) -> None:
    conn.execute(
        "INSERT INTO instruments (symbol, base, is_active, contract_details) "
        'VALUES (%s, %s, false, \'{"asset_class": "test"}\'::jsonb)',
        (symbol, symbol),
    )


def _cleanup(conn: psycopg.Connection, symbol: str) -> None:
    with conn.transaction():
        conn.execute("DELETE FROM ohlcv_coverage WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = %s", (symbol,))
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute("DELETE FROM ohlcv_intraday_raw_archive WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM ohlcv_request WHERE symbol = %s", (symbol,))
        conn.execute("SET LOCAL session_replication_role = origin")
        conn.execute("DELETE FROM instruments WHERE symbol = %s", (symbol,))


def _counts(conn: psycopg.Connection, symbol: str) -> tuple[int, int, int]:
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table} WHERE symbol = %s", (symbol,)).fetchone()[0]
        for table in ("ohlcv_request", "ohlcv_intraday_raw_archive", "ohlcv_coverage")
    )


def _chunk(symbol: str) -> tuple[list[tuple], list[tuple]]:
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    timestamps = [hour + timedelta(minutes=15 * i) for i in range(_N_BARS)]
    now = datetime.now(UTC)
    request = (
        uuid.uuid4(),
        uuid.uuid4(),
        symbol,
        "15m",
        "ibkr",
        "SMART",
        "TRADES",
        None,
        timestamps[0],
        timestamps[-1] + timedelta(minutes=15),
        None,
        "bars",
        None,
        None,
        _N_BARS,
        None,
        "test-189-01",
        now,
        now,
    )
    bars = [(ts, symbol, "15m", 10.0, 11.0, 9.0, 10.5, 100, "ibkr", None) for ts in timestamps]
    return [request], bars


@pytest.fixture()
def live():
    conn = psycopg.connect(_LIVE_DB_DSN, autocommit=True)
    symbol = _symbol()
    _register(conn, symbol)
    try:
        yield conn, symbol
    finally:
        _cleanup(conn, symbol)
        conn.close()


def _persist(conn: psycopg.Connection, symbol: str) -> tuple[int, int]:
    requests, bars = _chunk(symbol)
    return persist_chunk_atomically(
        conn,
        request_rows=requests,
        archive_rows=bars,
        write_archive_rows=insert_fetched_archive_rows,
        coverage=CoverageDelta(
            symbol=symbol, timeframe="15m", destination="archive", fetched_at=datetime.now(UTC)
        ),
    )


def test_request_bars_and_coverage_commit_together(live):
    conn, symbol = live
    assert _persist(conn, symbol) == (1, _N_BARS)
    assert _counts(conn, symbol) == (1, _N_BARS, 1)
    row = conn.execute(
        "SELECT row_count, last_fetch_status, consecutive_failures, "
        "earliest_timestamp < latest_timestamp FROM ohlcv_coverage WHERE symbol = %s",
        (symbol,),
    ).fetchone()
    assert row == (_N_BARS, "ok", 0, True)


def test_coverage_failure_after_the_bar_insert_commits_none_of_the_three(live, monkeypatch):
    conn, symbol = live

    def _boom(*_args, **_kwargs):
        raise RuntimeError("forced coverage failure")

    monkeypatch.setattr(_intraday_persist, "upsert_coverage", _boom)
    with pytest.raises(RuntimeError, match="forced coverage failure"):
        _persist(conn, symbol)
    assert _counts(conn, symbol) == (0, 0, 0)


def test_no_data_never_increments_consecutive_failures(live):
    conn, symbol = live
    observed = []
    for status in ("error", "error", "no_data", "error"):
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL ROLE bar_derivation_writer")
                record_fetch_outcome(cur, symbol, "15m", status, datetime.now(UTC))
        observed.append(
            conn.execute(
                "SELECT consecutive_failures FROM ohlcv_coverage "
                "WHERE symbol = %s AND timeframe = '15m'",
                (symbol,),
            ).fetchone()[0]
        )
    assert observed == [1, 2, 0, 1]


def test_refresh_1d_bounds_recomputes_from_the_canonical_rows(live):
    """Phase 189 plan 04: 1d bars are the daily stage's, so the fetcher recomputes the 1d
    ledger row from them; the fetch status and failure counter are left alone."""
    conn, symbol = live
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=d) for d in (3, 2, 1)]
    with conn.transaction():
        conn.execute("SET LOCAL ROLE bar_derivation_writer")
        cur = conn.cursor()
        record_fetch_outcome(cur, symbol, "1d", "error", datetime.now(UTC))
        cur.executemany(
            "INSERT INTO market_data_ohlcv "
            '("timestamp", symbol, timeframe, open, high, low, close, volume, source) '
            "VALUES (%s, %s, '1d', 10, 11, 9, 10.5, %s, 'ibkr')",
            # The zero-volume row is not tradeable and must not count.
            [(days[0], symbol, 100), (days[1], symbol, 100), (days[2], symbol, 0)],
        )
        assert refresh_1d_bounds(cur, [symbol, symbol]) == 1
    row = conn.execute(
        "SELECT earliest_timestamp, latest_timestamp, row_count, last_fetch_status, "
        "consecutive_failures FROM ohlcv_coverage WHERE symbol = %s AND timeframe = '1d'",
        (symbol,),
    ).fetchone()
    assert row == (days[0], days[1], 2, "error", 1)


def test_refresh_1d_bounds_with_no_symbols_issues_no_sql():
    class _NoSql:
        def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("no SQL expected")

    assert refresh_1d_bounds(_NoSql(), []) == 0
