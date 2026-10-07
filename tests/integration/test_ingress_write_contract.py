"""Integration: the ingress write contract under the real roles (phase 185 plan 39).

Runs on indicagent_test only (rebuilt by the integration conftest, migrations 443 and 448
replayed above the baseline cutoff; every fixture asserts the database name before any write).
persist_chunk_atomically runs as the production path does: SET LOCAL ROLE
ohlcv_observation_writer for the request rows, bar_derivation_writer for the bars, load record
and revisions. Grants are invisible to unit tests (docs/reference/gotchas.md), so this file is
the proof that the roles can do everything the contract asks: INSERT and upsert on
market_data_ohlcv and the archive, INSERT on ohlcv_load and ohlcv_revision, and UPDATE on the
archive that migration 448 grants.

Synthetic symbols are prefixed ZZ185 and removed afterwards. ohlcv_request, the archive and
ohlcv_observation refuse DELETE by trigger, so cleanup runs under session_replication_role =
replica inside a transaction scoped to the test symbol (test-only; production never deletes).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill import infrastructure_run_historical_pipeline as pipeline
from scripts.infrastructure.backfill._intraday_persist import chunk_digest, persist_chunk_atomically
from services.intraday_raw_archive import insert_fetched_archive_rows
from services.ohlcv_ingress_contract import RevisionRefused
from services.ohlcv_observation_writer import ObservationSink
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

_T0 = datetime(2021, 3, 1, 14, 30, tzinfo=UTC)


@pytest.fixture()
def db():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    symbol = f"ZZ185{uuid.uuid4().hex[:6].upper()}"
    conn.execute(
        "INSERT INTO instruments (symbol, base, is_active, contract_details) "
        'VALUES (%s, %s, false, \'{"asset_class": "test"}\'::jsonb)',
        (symbol, symbol),
    )
    try:
        yield conn, symbol
    finally:
        with conn.transaction():
            conn.execute("DELETE FROM ohlcv_coverage WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_revision WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_load WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("DELETE FROM ohlcv_intraday_raw_archive WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_observation WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_request WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = origin")
            conn.execute("DELETE FROM instruments WHERE symbol = %s", (symbol,))
        conn.close()


def _bars(symbol: str, tf: str, n: int, *, step_minutes: int, close: float = 10.5, archive=False):
    rows = []
    for i in range(n):
        row = (
            _T0 + timedelta(minutes=step_minutes * i),
            symbol,
            tf,
            10.0,
            11.0,
            9.0,
            close,
            100 + i,
            "ibkr",
        )
        rows.append(row + (None,) if archive else row)
    return rows


def _request(symbol: str, tf: str, rows: list[tuple]) -> tuple:
    now = datetime.now(UTC)
    return (
        uuid.uuid4(),
        uuid.uuid4(),
        symbol,
        tf,
        "ibkr",
        "SMART",
        "TRADES",
        None,
        rows[0][0],
        rows[-1][0] + timedelta(minutes=5),
        None,
        "bars",
        None,
        None,
        len(rows),
        None,
        "test-185-39",
        now,
        now,
    )


def _persist(conn, symbol, tf, rows, *, archive=False):
    return persist_chunk_atomically(
        conn,
        request_rows=[_request(symbol, tf, rows)],
        archive_rows=rows,
        write_archive_rows=(
            insert_fetched_archive_rows if archive else pipeline._insert_market_data_rows
        ),
    )


def _xmins(conn, table, symbol):
    return dict(
        conn.execute(
            f'SELECT "timestamp", xmin::text FROM {table} WHERE symbol = %s ORDER BY 1', (symbol,)
        ).fetchall()
    )


def _loads(conn, symbol):
    return conn.execute(
        "SELECT outcome, source, destination, n_bars, n_new, n_changed, n_unchanged "
        "FROM ohlcv_load WHERE symbol = %s ORDER BY loaded_at, load_id",
        (symbol,),
    ).fetchall()


def _n(conn, table, symbol):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE symbol = %s", (symbol,)).fetchone()[0]


def _digests(conn, symbol):
    return [
        r[0]
        for r in conn.execute(
            "SELECT content_digest FROM ohlcv_request WHERE symbol = %s ORDER BY requested_at",
            (symbol,),
        )
    ]


@pytest.mark.parametrize(
    ("table", "tf", "step", "archive"),
    [("market_data_ohlcv", "5m", 5, False), ("ohlcv_intraday_raw_archive", "15m", 15, True)],
)
def test_same_chunk_twice_then_one_changed_bar(db, table, tf, step, archive):
    conn, symbol = db
    rows = _bars(symbol, tf, 10, step_minutes=step, archive=archive)
    _persist(conn, symbol, tf, rows, archive=archive)
    first = _xmins(conn, table, symbol)
    assert len(first) == 10

    _persist(conn, symbol, tf, rows, archive=archive)
    assert _xmins(conn, table, symbol) == first  # no row rewritten
    assert _n(conn, "ohlcv_revision", symbol) == 0
    dest = "archive" if archive else "market_data_ohlcv"
    assert _loads(conn, symbol) == [
        ("applied", "ibkr", dest, 10, 10, 0, 0),
        ("applied", "ibkr", dest, 10, 0, 0, 10),
    ]

    restated = list(rows)
    restated[4] = restated[4][:6] + (10.75,) + restated[4][7:]
    _persist(conn, symbol, tf, restated, archive=archive)
    after = _xmins(conn, table, symbol)
    changed = [ts for ts in first if first[ts] != after[ts]]
    assert changed == [rows[4][0]]  # exactly one row rewritten
    assert conn.execute(
        f'SELECT close FROM {table} WHERE symbol = %s AND "timestamp" = %s', (symbol, rows[4][0])
    ).fetchone() == (10.75,)
    ((ts, old_close, old_source, origin),) = conn.execute(
        'SELECT "timestamp", old_close, old_source, origin FROM ohlcv_revision WHERE symbol = %s',
        (symbol,),
    ).fetchall()
    assert (ts, old_close, old_source, origin) == (rows[4][0], 10.5, "ibkr", "load")
    assert _loads(conn, symbol)[-1] == ("applied", "ibkr", dest, 10, 0, 1, 9)
    # Each request row carries the digest of the answer its chunk stored.
    assert _digests(conn, symbol) == [
        chunk_digest(rows),
        chunk_digest(rows),
        chunk_digest(restated),
    ]


def test_a_chunk_below_the_floor_with_restated_bars_is_written_not_refused(db):
    conn, symbol = db
    rows = _bars(symbol, "5m", 78, step_minutes=5)
    _persist(conn, symbol, "5m", rows)
    restated = [r[:6] + (10.9,) + r[7:] if i in (10, 11) else r for i, r in enumerate(rows)]
    _persist(conn, symbol, "5m", restated)  # 2 / 78 = 2.6% > 2%, but 78 < 500 stored
    assert _n(conn, "ohlcv_revision", symbol) == 2
    assert _loads(conn, symbol)[-1][4:] == (0, 2, 76)


def test_a_breaching_chunk_is_refused_and_recorded_with_bars_unchanged(db):
    conn, symbol = db
    rows = _bars(symbol, "5m", 600, step_minutes=5)
    _persist(conn, symbol, "5m", rows)
    before = _xmins(conn, "market_data_ohlcv", symbol)
    restated = [r[:6] + (10.9,) + r[7:] if i < 20 else r for i, r in enumerate(rows)]  # 3.3%
    with pytest.raises(RevisionRefused):
        _persist(conn, symbol, "5m", restated)
    assert _xmins(conn, "market_data_ohlcv", symbol) == before
    assert _n(conn, "ohlcv_revision", symbol) == 0
    outcome, _source, _dest, n_bars, n_new, n_changed, n_unchanged = _loads(conn, symbol)[-1]
    assert (outcome, n_bars, n_new, n_changed, n_unchanged) == ("refused", 600, 0, 0, 0)
    detail = conn.execute(
        "SELECT detail FROM ohlcv_load WHERE symbol = %s AND outcome = 'refused'", (symbol,)
    ).fetchone()[0]
    assert "changed 20 / stored 600" in detail
    # The refused answer is still recorded, with no digest (nothing was stored).
    assert _digests(conn, symbol) == [chunk_digest(rows), None]


def test_the_archive_refuses_delete_and_accepts_update(db):
    conn, symbol = db
    rows = _bars(symbol, "15m", 3, step_minutes=15, archive=True)
    _persist(conn, symbol, "15m", rows, archive=True)
    with pytest.raises(psycopg.errors.CheckViolation, match="refuses DELETE"):
        conn.execute("DELETE FROM ohlcv_intraday_raw_archive WHERE symbol = %s", (symbol,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("TRUNCATE ohlcv_intraday_raw_archive")
    conn.execute("UPDATE ohlcv_intraday_raw_archive SET close = 10.6 WHERE symbol = %s", (symbol,))
    assert _n(conn, "ohlcv_intraday_raw_archive", symbol) == 3


@pytest.mark.parametrize(
    ("table", "tf", "step", "archive"),
    [("market_data_ohlcv", "5m", 5, False), ("ohlcv_intraday_raw_archive", "15m", 15, True)],
)
def test_a_restated_bar_in_a_compressed_chunk_is_rewritten_under_the_real_role(
    db, table, tf, step, archive
):
    conn, symbol = db
    rows = _bars(symbol, tf, 10, step_minutes=step, archive=archive)
    _persist(conn, symbol, tf, rows, archive=archive)
    chunks = [
        r[0]
        for r in conn.execute(
            "SELECT format('%%I.%%I', chunk_schema, chunk_name) "
            "FROM timescaledb_information.chunks WHERE hypertable_name = %s",
            (table,),
        )
    ]
    compressed = 0
    for chunk in chunks:
        try:
            conn.execute("SELECT compress_chunk(%s::regclass, if_not_compressed => true)", (chunk,))
            compressed += 1
        except psycopg.Error:
            pass
    if not compressed:
        pytest.skip(f"{table} has no compressible chunk on this test database")
    restated = list(rows)
    restated[2] = restated[2][:6] + (10.8,) + restated[2][7:]
    _persist(conn, symbol, tf, restated, archive=archive)
    assert conn.execute(
        f'SELECT close FROM {table} WHERE symbol = %s AND "timestamp" = %s', (symbol, rows[2][0])
    ).fetchone() == (10.8,)
    assert _n(conn, table, symbol) == 10
    assert _n(conn, "ohlcv_revision", symbol) == 1


def test_d1_elision_under_the_real_role_stores_a_changed_answer_once(db):
    from src.providers.base import OHLCVBar

    conn, symbol = db

    def run(close: float) -> None:
        sink = ObservationSink(conn, caller="ibkr-history-fetch")
        now = datetime.now(UTC)
        record = type(
            "R",
            (),
            dict(
                request_id=str(uuid.uuid4()),
                fetch_run_id=str(uuid.uuid4()),
                symbol=symbol,
                timeframe="1d",
                route="SMART",
                what_to_show="TRADES",
                primary_exchange=None,
                window_start=None,
                window_end=now,
                ib_req_id=None,
                outcome="bars",
                error_code=None,
                error_text=None,
                n_bars=2,
                client_id=None,
                requested_at=now,
                answered_at=now,
            ),
        )()
        bars = [
            OHLCVBar(
                symbol=symbol,
                timeframe="1d",
                timestamp=datetime(2024, 1, 2 + i, tzinfo=UTC),
                open=100.0,
                high=101.0,
                low=99.0,
                close=close,
                volume=1000,
                source="ibkr",
            )
            for i in range(2)
        ]
        sink.on_request(record)
        sink.on_observation(record, bars)
        sink.flush()

    run(100.5)
    run(100.5)  # identical answer: no observation stored again
    n_obs = conn.execute("SELECT count(*) FROM ohlcv_observation WHERE symbol = %s", (symbol,))
    assert n_obs.fetchone()[0] == 2
    run(101.5)  # restated: both dates land
    assert (
        conn.execute(
            "SELECT count(*) FROM ohlcv_observation WHERE symbol = %s", (symbol,)
        ).fetchone()[0]
        == 4
    )
    # Every answer is still recorded in the request ledger with its full length.
    assert conn.execute(
        "SELECT count(*), sum(n_bars) FROM ohlcv_request WHERE symbol = %s", (symbol,)
    ).fetchone() == (3, 6)
