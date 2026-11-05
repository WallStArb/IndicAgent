"""Integration: the raw-first ingress contract under the real roles (phase 185 plan 39; 191-05).

Runs on indicagent_test only (rebuilt by the integration conftest, migrations 443 and 448
replayed above the baseline cutoff; every fixture asserts the database name before any write).
persist_chunk_atomically runs as the production path does: the contract's settings are read as
the connection's user, then SET LOCAL ROLE bar_derivation_writer for the raw rows, load record,
revisions and canonical selection, and SET LOCAL ROLE ohlcv_observation_writer for the request
rows. Grants are invisible to unit tests (docs/reference/gotchas.md), so this file is the proof
that the roles can do everything the contract asks: INSERT and upsert on ohlcv_raw and
market_data_ohlcv, INSERT on ohlcv_load and ohlcv_revision, COPY into ohlcv_request.

Synthetic symbols are prefixed ZZ185 and removed afterwards. ohlcv_request refuses DELETE by
trigger, so cleanup runs under session_replication_role = replica inside a transaction scoped to
the test symbol (test-only; production never deletes).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from scripts.infrastructure.backfill._intraday_persist import chunk_digest, persist_chunk_atomically
from services.bar_load import load_frame
from services.ohlcv_coverage_writer import CoverageDelta
from services.ohlcv_raw_writer import RawRow
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
    # The test database holds no policy data: canonical selection of the 5m rows reads a
    # symbol-scoped direct IBKR row (the live 5m default is IBKR before 2016, Alpaca after).
    conn.execute(
        "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, ingress_mode, "
        "primary_source, reason) VALUES ('5m', %s, '1990-01-01', 'direct', 'ibkr', 'test')",
        (symbol,),
    )
    try:
        yield conn, symbol
    finally:
        with conn.transaction():
            conn.execute("DELETE FROM ohlcv_coverage WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_raw WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_revision WHERE symbol = %s", (symbol,))
            # The restatement detector's flags (FK to the load) and the 1d selection's session
            # choices, both written by the contract under test.
            conn.execute("DELETE FROM ohlcv_restatement_flag WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM bar_session_choice WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_load WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("DELETE FROM ohlcv_request WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM bar_source_policy WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = origin")
            conn.execute("DELETE FROM instruments WHERE symbol = %s", (symbol,))
        conn.close()


def _request(symbol: str, tf: str, rows: list, *, what_to_show: str = "TRADES") -> tuple:
    now = datetime.now(UTC)
    return (
        uuid.uuid4(),
        uuid.uuid4(),
        symbol,
        tf,
        "ibkr",
        "SMART",
        what_to_show,
        None,
        rows[0].timestamp,
        rows[-1].timestamp + timedelta(minutes=5),
        None,
        "bars",
        None,
        None,
        len(rows),
        None,
        "test-185-39",
        now,
        now,
        None,  # partial_bars (migration 479)
    )


def _persist(conn, symbol, tf, rows, *, coverage=False, **kwargs):
    return persist_chunk_atomically(
        conn,
        request_rows=[_request(symbol, tf, rows)],
        raw_rows=rows,
        coverage=(
            CoverageDelta(symbol, tf, "raw", fetched_at=datetime.now(UTC)) if coverage else None
        ),
        **kwargs,
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


def _chunk(symbol, tf, n, *, step_minutes, close=10.5, vendor="ibkr", kind="named"):
    return [
        RawRow(
            timestamp=_T0 + timedelta(minutes=step_minutes * i),
            symbol=symbol,
            timeframe=tf,
            vendor=vendor,
            kind=kind,
            open=10.0,
            high=11.0,
            low=9.0,
            close=close,
            volume=100 + i,
        )
        for i in range(n)
    ]


@pytest.mark.parametrize(("tf", "step"), [("5m", 5), ("15m", 15)])
def test_same_chunk_twice_then_one_changed_bar(db, tf, step):
    conn, symbol = db
    rows = _chunk(symbol, tf, 10, step_minutes=step)
    _persist(conn, symbol, tf, rows)
    first = _xmins(conn, "ohlcv_raw", symbol)
    assert len(first) == 10

    _persist(conn, symbol, tf, rows)
    assert _xmins(conn, "ohlcv_raw", symbol) == first  # no row rewritten
    assert _n(conn, "ohlcv_revision", symbol) == 0
    assert _loads(conn, symbol) == [
        ("applied", "ibkr", "raw", 10, 10, 0, 0),
        ("applied", "ibkr", "raw", 10, 0, 0, 10),
    ]

    restated = list(rows)
    restated[4] = RawRow(**{**rows[4].__dict__, "close": 10.75})
    _persist(conn, symbol, tf, restated)
    after = _xmins(conn, "ohlcv_raw", symbol)
    changed = [ts for ts in first if first[ts] != after[ts]]
    assert changed == [rows[4].timestamp]  # exactly one row rewritten
    assert conn.execute(
        'SELECT close FROM ohlcv_raw WHERE symbol = %s AND "timestamp" = %s',
        (symbol, rows[4].timestamp),
    ).fetchone() == (10.75,)
    ((ts, old_close, old_source, origin, vendor, kind),) = conn.execute(
        'SELECT "timestamp", old_close, old_source, origin, vendor, kind FROM ohlcv_revision '
        "WHERE symbol = %s",
        (symbol,),
    ).fetchall()
    assert (ts, old_close, origin, vendor, kind) == (
        rows[4].timestamp,
        10.5,
        "raw",
        "ibkr",
        "named",
    )
    assert _loads(conn, symbol)[-1] == ("applied", "ibkr", "raw", 10, 0, 1, 9)
    # Each request row carries the digest of the answer its chunk stored.
    assert _digests(conn, symbol) == [
        chunk_digest(rows),
        chunk_digest(rows),
        chunk_digest(restated),
    ]


def test_a_small_restatement_is_written_last_wins(db):
    conn, symbol = db
    rows = _chunk(symbol, "5m", 78, step_minutes=5)
    _persist(conn, symbol, "5m", rows)
    restated = [
        RawRow(**{**r.__dict__, "close": 10.9}) if i in (10, 11) else r for i, r in enumerate(rows)
    ]
    result = _persist(conn, symbol, "5m", restated)
    assert result.ingress.n_changed == 2
    assert _n(conn, "ohlcv_revision", symbol) == 2
    assert _loads(conn, symbol)[-1][4:] == (0, 2, 76)


def test_a_large_restatement_is_written_last_wins_and_recoverable(db):
    """D-191-N (owner 2026-10-14): no load-level refusal and nothing held. A vendor's re-serve of
    its own history replaces raw last-wins, canonical follows, and every old value is recoverable
    from ohlcv_revision (origin raw); the restatement detector flags, it never blocks."""
    conn, symbol = db
    rows = _chunk(symbol, "5m", 600, step_minutes=5)
    _persist(conn, symbol, "5m", rows)
    restated = [
        RawRow(**{**r.__dict__, "close": 10.9}) if i < 20 else r for i, r in enumerate(rows)
    ]
    result = _persist(conn, symbol, "5m", restated)
    assert (result.ingress.n_changed, result.ingress.n_unchanged) == (20, 580)
    assert conn.execute(
        "SELECT count(*) FROM ohlcv_raw WHERE symbol = %s AND close = 10.9", (symbol,)
    ).fetchone() == (20,)
    assert conn.execute(
        "SELECT count(*) FROM market_data_ohlcv WHERE symbol = %s AND close = 10.9", (symbol,)
    ).fetchone() == (20,)
    assert conn.execute(
        "SELECT origin, count(*), min(old_close) FROM ohlcv_revision WHERE symbol = %s "
        "GROUP BY origin",
        (symbol,),
    ).fetchall() == [("raw", 20, 10.5)]
    assert _loads(conn, symbol)[-1] == ("applied", "ibkr", "raw", 600, 0, 20, 580)
    assert _digests(conn, symbol) == [chunk_digest(rows), chunk_digest(restated)]


def test_a_restated_bar_in_a_compressed_chunk_is_rewritten_under_the_real_role(db):
    conn, symbol = db
    rows = _chunk(symbol, "5m", 10, step_minutes=5)
    _persist(conn, symbol, "5m", rows)
    chunks = [
        r[0]
        for r in conn.execute(
            "SELECT format('%%I.%%I', chunk_schema, chunk_name) "
            "FROM timescaledb_information.chunks WHERE hypertable_name = 'ohlcv_raw'"
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
        pytest.skip("ohlcv_raw has no compressible chunk on this test database")
    restated = list(rows)
    restated[2] = RawRow(**{**rows[2].__dict__, "close": 10.8})
    _persist(conn, symbol, "5m", restated)
    assert conn.execute(
        'SELECT close FROM ohlcv_raw WHERE symbol = %s AND "timestamp" = %s',
        (symbol, rows[2].timestamp),
    ).fetchone() == (10.8,)
    assert _n(conn, "ohlcv_raw", symbol) == 10
    assert _n(conn, "ohlcv_revision", symbol) == 1


def test_a_1d_answer_lands_with_the_kind_its_request_carries(db):
    """A daily answer is a (vendor, kind) of its own: SMART TRADES and a listing-venue route are
    two raw rows of one session, never one row revised (T-191-16, migration 476)."""
    conn, symbol = db
    smart = _chunk(symbol, "1d", 3, step_minutes=1440, kind="smart_trades")
    venue = _chunk(symbol, "1d", 3, step_minutes=1440, close=10.6, kind="venue_nyse")
    _persist(conn, symbol, "1d", smart)
    _persist(conn, symbol, "1d", venue)
    assert conn.execute(
        "SELECT vendor, kind, count(*) FROM ohlcv_raw WHERE symbol = %s GROUP BY 1, 2 ORDER BY 2",
        (symbol,),
    ).fetchall() == [("ibkr", "smart_trades", 3), ("ibkr", "venue_nyse", 3)]
    assert _n(conn, "ohlcv_revision", symbol) == 0  # a route difference is never a revision
    assert _n(conn, "market_data_ohlcv", symbol) == 0  # 1d has no canonical selection here


def test_request_rows_and_raw_rows_roll_back_together(db):
    conn, symbol = db
    rows = _chunk(symbol, "5m", 5, step_minutes=5, kind="no_such_kind")
    with pytest.raises(ValueError, match="not a CVR bar_kind code"):
        _persist(conn, symbol, "5m", rows)
    assert _n(conn, "ohlcv_request", symbol) == 0
    assert _n(conn, "ohlcv_raw", symbol) == 0
    assert _n(conn, "ohlcv_load", symbol) == 0


def test_coverage_moves_with_the_new_rows_in_the_same_transaction(db):
    conn, symbol = db
    rows = _chunk(symbol, "5m", 5, step_minutes=5)
    _persist(conn, symbol, "5m", rows, coverage=True)
    _persist(conn, symbol, "5m", rows, coverage=True)  # unchanged re-offer adds no rows
    assert conn.execute(
        "SELECT row_count, last_fetch_status FROM ohlcv_coverage "
        "WHERE symbol = %s AND timeframe = '5m'",
        (symbol,),
    ).fetchone() == (5, "ok")


def test_the_loader_offers_every_row_to_raw_or_the_pending_list(db):
    """Port of the no-drop assertion (todo 528 R1): every offered row appears in ohlcv_raw,
    regular-hours and extended-hours rows alike; a later answer restating the vendor's own
    history replaces it last-wins with the old values in ohlcv_revision (D-191-N)."""
    import pandas as pd

    conn, symbol = db
    stamps = [pd.Timestamp(_T0 + timedelta(minutes=5 * i)) for i in range(600)]
    stamps[0] = pd.Timestamp("2021-03-01 09:00:00", tz="UTC")  # pre-market

    def frame(close: float) -> pd.DataFrame:
        return pd.DataFrame({"t": stamps, "o": 10.0, "h": 11.0, "l": 9.0, "c": close, "v": 100})

    first = load_frame(
        conn,
        symbol,
        frame(10.5),
        vendor="alpaca",
        kind="sip_rth",
        timeframe="5m",
        caller="alpaca-5m-load",
        write=True,
        answered_at=datetime.now(UTC),
    )
    assert (first.n_offered, first.n_new) == (600, 600)
    assert _n(conn, "ohlcv_raw", symbol) == 600
    assert conn.execute(
        "SELECT DISTINCT vendor, kind FROM ohlcv_raw WHERE symbol = %s", (symbol,)
    ).fetchall() == [("alpaca", "sip_rth")]
    second = load_frame(
        conn,
        symbol,
        frame(11.5),
        vendor="alpaca",
        kind="sip_rth",
        timeframe="5m",
        caller="alpaca-5m-load",
        write=True,
        answered_at=datetime.now(UTC),
    )  # restates all 600 of its own stored rows: written last-wins
    assert (second.n_new, second.n_changed) == (0, 600)
    assert _n(conn, "ohlcv_raw", symbol) == 600
    assert conn.execute(
        "SELECT count(*), min(old_close) FROM ohlcv_revision WHERE symbol = %s AND origin = 'raw'",
        (symbol,),
    ).fetchone() == (600, 10.5)
    assert conn.execute(
        "SELECT min(close), max(close) FROM ohlcv_raw WHERE symbol = %s", (symbol,)
    ).fetchone() == (11.5, 11.5)


# --- apply_raw_contract under the real role (phase 191 plan 04) ------------------------------

from services.ohlcv_ingress_contract import apply_raw_contract, read_raw_params  # noqa: E402


def _raw_rows(symbol, n, *, vendor="ibkr", kind="named", close=10.5, tf="5m"):
    return [
        RawRow(
            timestamp=_T0 + timedelta(minutes=5 * i),
            symbol=symbol,
            timeframe=tf,
            vendor=vendor,
            kind=kind,
            open=10.0,
            high=11.0,
            low=9.0,
            close=close,
            volume=100 + i,
        )
        for i in range(n)
    ]


def _raw_cleanup(conn, symbol):
    with conn.transaction():
        conn.execute("DELETE FROM ohlcv_raw WHERE symbol = %s", (symbol,))


def _apply_raw(conn, rows, *, caller="ibkr-history-fetch"):
    request = uuid.uuid4()
    with conn.transaction():
        with conn.cursor() as cur:
            params = read_raw_params(cur)
        conn.execute("SET LOCAL ROLE bar_derivation_writer")
        return apply_raw_contract(
            conn,
            rows,
            caller=caller,
            request_id=request,
            answered_at=datetime.now(UTC),
            params=params,
        )


def test_raw_contract_records_raw_then_selects_canonical_under_the_role(db):
    conn, symbol = db
    try:
        result = _apply_raw(conn, _raw_rows(symbol, 10))
        assert (result.n_new, result.n_changed) == (10, 0)
        assert result.selected_slots == 10
        assert _n(conn, "ohlcv_raw", symbol) == 10 and _n(conn, "market_data_ohlcv", symbol) == 10
        assert _loads(conn, symbol) == [("applied", "ibkr", "raw", 10, 10, 0, 0)]
        again = _apply_raw(conn, _raw_rows(symbol, 10))
        assert (again.n_new, again.n_changed, again.n_unchanged) == (0, 0, 10)
    finally:
        _raw_cleanup(conn, symbol)


def test_raw_contract_cross_vendor_difference_writes_no_revision(db):
    conn, symbol = db
    try:
        _apply_raw(conn, _raw_rows(symbol, 10))
        other = _apply_raw(
            conn,
            _raw_rows(symbol, 10, vendor="alpaca", kind="sip_rth", close=99.0),
            caller="alpaca-5m-load",
        )
        assert other.n_new == 10
        assert _n(conn, "ohlcv_revision", symbol) == 0
        assert _n(conn, "ohlcv_raw", symbol) == 20
    finally:
        _raw_cleanup(conn, symbol)


def test_raw_contract_self_restatement_is_logged_with_vendor_and_kind(db):
    conn, symbol = db
    try:
        _apply_raw(conn, _raw_rows(symbol, 10))
        restated = _apply_raw(conn, _raw_rows(symbol, 10, close=10.75))
        assert restated.n_changed == 10
        rows = conn.execute(
            "SELECT vendor, kind, origin, old_close FROM ohlcv_revision WHERE symbol = %s",
            (symbol,),
        ).fetchall()
        assert len(rows) == 10 and set(rows) == {("ibkr", "named", "raw", 10.5)}
    finally:
        _raw_cleanup(conn, symbol)


def test_raw_contract_restatement_reaches_canonical_and_stays_recoverable(db):
    """D-191-N replaces the refusal this test once pinned (review finding 4 of 191-07): a
    vendor restating 50 of its own 600 stored rows is written last-wins, canonical selection
    promotes the new values, an unchanged re-offer changes nothing more, and the old values sit
    in ohlcv_revision (origin raw), never as pending holds."""
    conn, symbol = db
    try:
        _apply_raw(conn, _raw_rows(symbol, 600))
        restated = [
            r if i >= 50 else RawRow(**{**r.__dict__, "close": 77.0})
            for i, r in enumerate(_raw_rows(symbol, 600))
        ]
        first = _apply_raw(conn, restated)
        assert first.n_changed == 50 and first.selected_slots == 50  # the touched slots
        again = _apply_raw(conn, restated)
        assert (again.n_changed, again.n_unchanged) == (0, 600)
        for table in ("ohlcv_raw", "market_data_ohlcv"):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE symbol = %s AND close = 77.0", (symbol,)
            ).fetchone() == (50,)
        assert conn.execute(
            "SELECT origin, count(*), min(old_close), max(old_close) FROM ohlcv_revision "
            "WHERE symbol = %s GROUP BY origin",
            (symbol,),
        ).fetchall() == [("raw", 50, 10.5, 10.5)]
    finally:
        _raw_cleanup(conn, symbol)
