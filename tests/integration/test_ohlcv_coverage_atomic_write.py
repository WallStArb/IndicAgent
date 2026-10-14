"""Live-DB proof of the three-way atomic write (phase 189 plan 01, CD-04, CD-05, CD-14).

Runs on indicagent_test (rebuilt by the integration conftest; moved here from tests/unit/scripts
in plan 185-39, todo 494: it used to write the live database, and the ingress contract's
ohlcv_load rows would have left ZZ189 residue there). Real tables, real NOLOGIN roles and
grants: a request row, the raw rows and the ohlcv_coverage row either all commit or none do. Since
phase 191 plan 06 the ledger is per source: a row counts the provider's own ohlcv_raw rows.
Every fixture asserts the database name before any write.

Each case uses its own synthetic symbol (ZZ189 + random hex) at the current UTC hour, so the
raw rows land in an uncompressed chunk and no real series is touched. ohlcv_request has an
FK to instruments, so the case registers the symbol as an inactive instrument first.

Cleanup: ohlcv_request (migration 380) is append-only by trigger, so removing the synthetic rows
needs session_replication_role = replica for that DELETE, inside a transaction scoped to the test
symbol. That bypass is test-only; production code never deletes a request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill import _intraday_persist
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import (
    CoverageDelta,
    rebuild_from_stored_state,
    record_fetch_outcome,
    refresh_1d_bounds,
    upsert_coverage,
)
from services.ohlcv_raw_writer import RawRow
from tests.integration.conftest import TEST_DB_URL

_N_BARS = 3

pytestmark = pytest.mark.integration


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
        conn.execute("DELETE FROM ohlcv_raw WHERE symbol = %s", (symbol,))
        # The ingress contract writes ohlcv_load (FK RESTRICT on instruments) and revisions.
        conn.execute("DELETE FROM ohlcv_revision WHERE symbol = %s", (symbol,))
        conn.execute("DELETE FROM ohlcv_load WHERE symbol = %s", (symbol,))
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute("DELETE FROM ohlcv_request WHERE symbol = %s", (symbol,))
        conn.execute("SET LOCAL session_replication_role = origin")
        conn.execute("DELETE FROM instruments WHERE symbol = %s", (symbol,))


def _counts(conn: psycopg.Connection, symbol: str) -> tuple[int, int, int]:
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table} WHERE symbol = %s", (symbol,)).fetchone()[0]
        for table in ("ohlcv_request", "ohlcv_raw", "ohlcv_coverage")
    )


def _chunk(symbol: str) -> tuple[list[tuple], list[RawRow]]:
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
    bars = [
        RawRow(ts, symbol, "15m", "ibkr", "generic", 10.0, 11.0, 9.0, 10.5, 100)
        for ts in timestamps
    ]
    return [request], bars


@pytest.fixture()
def live():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    symbol = _symbol()
    _register(conn, symbol)
    try:
        yield conn, symbol
    finally:
        _cleanup(conn, symbol)
        conn.close()


def _persist(conn: psycopg.Connection, symbol: str) -> tuple[int, int]:
    requests, bars = _chunk(symbol)
    result = persist_chunk_atomically(
        conn,
        request_rows=requests,
        raw_rows=bars,
        coverage=CoverageDelta(
            symbol=symbol, timeframe="15m", destination="raw", fetched_at=datetime.now(UTC)
        ),
    )
    return result.n_requests, result.n_rows


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


def _insert_raw(conn, symbol, timeframe, vendor, kind, stamps, volume=100):
    conn.cursor().executemany(
        "INSERT INTO ohlcv_raw "
        '("timestamp", symbol, timeframe, vendor, kind, open, high, low, close, volume) '
        "VALUES (%s, %s, %s, %s, %s, 10, 11, 9, 10.5, %s)",
        [(ts, symbol, timeframe, vendor, kind, volume) for ts in stamps],
    )


def test_refresh_1d_bounds_recomputes_from_the_providers_own_raw_rows(live):
    """The fetcher recomputes the 1d ledger row from the vendor's raw rows (a 1d answer carries
    no coverage delta); the fetch status and failure counter are left alone. A slot counts once
    whatever its kinds, zero-volume rows count (raw holds everything the vendor served), and
    another vendor's rows never enter the row."""
    conn, symbol = live
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=d) for d in (3, 2, 1)]
    with conn.transaction():
        _insert_raw(conn, symbol, "1d", "ibkr", "smart_trades", [days[0], days[1]])
        _insert_raw(conn, symbol, "1d", "ibkr", "smart_adjusted", [days[1]])
        _insert_raw(conn, symbol, "1d", "ibkr", "venue_nyse", [days[2]], volume=0)
        _insert_raw(conn, symbol, "1d", "tradier", "consolidated", [today - timedelta(days=9)])
        conn.execute("SET LOCAL ROLE bar_derivation_writer")
        cur = conn.cursor()
        record_fetch_outcome(cur, symbol, "1d", "error", datetime.now(UTC))
        assert refresh_1d_bounds(cur, [symbol, symbol]) == 1
        assert refresh_1d_bounds(cur, [symbol], provider="tradier") == 1
    row = conn.execute(
        "SELECT earliest_timestamp, latest_timestamp, row_count, last_fetch_status, "
        "consecutive_failures FROM ohlcv_coverage "
        "WHERE symbol = %s AND timeframe = '1d' AND provider = 'ibkr'",
        (symbol,),
    ).fetchone()
    assert row == (days[0], days[2], 3, "error", 1)
    assert conn.execute(
        "SELECT row_count FROM ohlcv_coverage WHERE symbol = %s AND provider = 'tradier'",
        (symbol,),
    ).fetchone() == (1,)


def test_refresh_1d_bounds_with_no_symbols_issues_no_sql():
    class _NoSql:
        def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("no SQL expected")

    assert refresh_1d_bounds(_NoSql(), []) == 0


def test_rebuild_from_stored_state_recomputes_stale_rows_in_place(live):
    """189-06: a writer that stored bars around the ledger (the todo 449 lane, coverage=None)
    leaves the row stale; the rebuild recomputes its bounds and count from the vendor's raw
    rows and keeps the failure counter, and a scoped rebuild touches only its symbol."""
    conn, symbol = live
    _persist(conn, symbol)  # ledger row: _N_BARS rows, ok, 0 failures
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    # Two more raw rows stored with no coverage delta, as the lane did, plus one charged failure.
    with conn.transaction():
        _insert_raw(
            conn,
            symbol,
            "15m",
            "ibkr",
            "named",
            [hour + timedelta(minutes=15 * i) for i in (_N_BARS, _N_BARS + 1)],
        )
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            record_fetch_outcome(cur, symbol, "15m", "error", datetime.now(UTC))
    before = conn.execute(
        "SELECT row_count, latest_timestamp FROM ohlcv_coverage "
        "WHERE symbol = %s AND timeframe = '15m'",
        (symbol,),
    ).fetchone()
    assert before[0] == _N_BARS
    other_before = conn.execute(
        "SELECT count(*), sum(row_count) FROM ohlcv_coverage WHERE symbol <> %s", (symbol,)
    ).fetchone()

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            assert rebuild_from_stored_state(cur, [symbol], provider="ibkr") == 1
            assert rebuild_from_stored_state(cur, [], provider="ibkr") == 0

    row = conn.execute(
        "SELECT earliest_timestamp, latest_timestamp, row_count, consecutive_failures, "
        "last_fetch_status FROM ohlcv_coverage WHERE symbol = %s AND timeframe = '15m'",
        (symbol,),
    ).fetchone()
    assert row[0] == hour
    assert row[1] == hour + timedelta(minutes=15 * (_N_BARS + 1))
    assert row[2] == _N_BARS + 2
    # The failure counter is the fetcher's own; the request (older) does not override the
    # newer error outcome.
    assert row[3:] == (1, "error")
    assert (
        conn.execute(
            "SELECT count(*), sum(row_count) FROM ohlcv_coverage WHERE symbol <> %s", (symbol,)
        ).fetchone()
        == other_before
    )


def test_rebuild_counts_each_providers_own_raw_rows_whatever_is_canonical(live):
    """Raw is per source: the ibkr row counts every ibkr raw row of the series, including slots
    alpaca also holds (and might win canonically), and the alpaca row counts alpaca's. A rebuild
    with provider None covers every provider, and an unknown provider raises before any SQL."""
    conn, symbol = live
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    slots = [hour + timedelta(minutes=5 * i) for i in range(6)]
    with conn.transaction():
        _insert_raw(conn, symbol, "5m", "ibkr", "named", slots[:4])
        _insert_raw(conn, symbol, "5m", "alpaca", "sip_rth", slots[2:], volume=0)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            assert rebuild_from_stored_state(cur, [symbol]) == 2
            with pytest.raises(ValueError, match="unknown coverage provider"):
                rebuild_from_stored_state(cur, [symbol], provider="tradier")
    rows = conn.execute(
        "SELECT provider, row_count, earliest_timestamp, latest_timestamp FROM ohlcv_coverage "
        "WHERE symbol = %s AND timeframe = '5m' ORDER BY provider",
        (symbol,),
    ).fetchall()
    assert rows == [("alpaca", 4, slots[2], slots[5]), ("ibkr", 4, slots[0], slots[3])]
    for provider, count, earliest, latest in rows:
        assert conn.execute(
            'SELECT count(*), min("timestamp"), max("timestamp") FROM ohlcv_raw '
            "WHERE symbol = %s AND timeframe = '5m' AND vendor = %s",
            (symbol, provider),
        ).fetchone() == (count, earliest, latest)


# ---------------------------------------------------------------------------
# The live post-flip shape (phase 190 plan 02, applied at the 190-06 cutover): a second
# provider upserts a DISTINCT row. Through waves 1-4 this case simulated the WHOLE flip
# inside one force-rolled-back transaction (465 was committed but un-applied); since the
# cutover the live schema carries the (symbol, timeframe, provider) PK and the writer
# targets it, so the assertion runs directly against indicagent_test. upsert_coverage is
# called directly: persist_chunk_atomically demands an idle connection and the fixture
# owns cleanup.
# ---------------------------------------------------------------------------


def test_a_second_provider_upserts_a_distinct_row(live):
    conn, symbol = live
    now = datetime.now(UTC)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            delta = dict(symbol=symbol, timeframe="15m", destination="raw", fetched_at=now)
            upsert_coverage(
                cur,
                CoverageDelta(**delta, provider="ibkr"),
                earliest=now,
                latest=now,
                n_new_rows=3,
            )
            upsert_coverage(
                cur,
                CoverageDelta(**delta, provider="alpaca"),
                earliest=now,
                latest=now,
                n_new_rows=2,
            )
            rows = cur.execute(
                "SELECT provider, row_count FROM ohlcv_coverage "
                "WHERE symbol = %s AND timeframe = '15m' ORDER BY provider",
                (symbol,),
            ).fetchall()
            assert rows == [("alpaca", 2), ("ibkr", 3)]


def test_rebuild_zeroes_a_provider_row_with_no_raw_and_no_requests(live):
    """Review finding 4 (plan 191-06): a pre-191 Tradier-era 1d bound under the ibkr label, with
    no ibkr raw row and no ibkr request, is zeroed; a row that still has raw is untouched, and
    the fetcher's own state (status, failure counter) is never touched."""
    conn, symbol = live
    day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with conn.transaction():
        _insert_raw(conn, symbol, "1d", "tradier", "consolidated", [day - timedelta(days=2)])
        conn.execute(
            "INSERT INTO ohlcv_coverage (symbol, timeframe, earliest_timestamp, latest_timestamp, "
            "row_count, provider, last_fetch_status, consecutive_failures) "
            "VALUES (%s, '1d', %s, %s, 2954, 'ibkr', 'error', 6)",
            (symbol, day - timedelta(days=9), day - timedelta(days=2)),
        )
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            assert rebuild_from_stored_state(cur, [symbol], provider="ibkr") == 1
    assert conn.execute(
        "SELECT earliest_timestamp, latest_timestamp, row_count, last_fetch_status, "
        "consecutive_failures FROM ohlcv_coverage WHERE symbol = %s AND provider = 'ibkr'",
        (symbol,),
    ).fetchone() == (None, None, 0, "error", 6)
