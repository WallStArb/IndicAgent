"""The bulk path's SQL against the row path on the same stored rows (bulk raw load path design,
build step 2): the classification CASE, the serve-time split, the revision and raw statements.

TEMP tables shadow ohlcv_raw and ohlcv_revision (pg_temp is searched first) inside a transaction
the fixture always rolls back; each path runs in its own savepoint over the same seeded rows, so
no live row is read or written. Edge cases the month-scale proof
(scripts/ops/bars/ops_raw_bulk_equivalence.py) may not meet: -0.0 against 0.0, NULL volume on
either side, a stored NULL served_at, an equal serve time, a one-ulp price change, a per-row serve
time split around the stored one, and a stored row moved under the lock.
"""

from __future__ import annotations

import functools
import math
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from services.ohlcv_raw_writer import (
    RawRow,
    build_raw_batch,
    datetime_to_us,
    stage_and_classify,
    write_classified,
    write_raw,
)

pytestmark = pytest.mark.live_db

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"
VENDORS, KINDS = {"massive"}, {"sip_flat_agg"}
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
T0 = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
SERVED = datetime(2024, 6, 4, tzinfo=UTC)
OLD_REQUEST = uuid.UUID("00000000-0000-0000-0000-00000000000a")
OLD_LOAD = uuid.UUID("00000000-0000-0000-0000-00000000000b")

_SHADOW_DDL = (
    'CREATE TEMP TABLE ohlcv_raw ("timestamp" timestamptz NOT NULL, symbol text NOT NULL, '
    "timeframe text NOT NULL, vendor text NOT NULL, kind text NOT NULL, open float8 NOT NULL, "
    "high float8 NOT NULL, low float8 NOT NULL, close float8 NOT NULL, volume bigint, "
    "served_at timestamptz, request_id uuid, load_id uuid, "
    'PRIMARY KEY ("timestamp", symbol, timeframe, vendor, kind))',
    "CREATE TEMP TABLE ohlcv_revision (load_id uuid NOT NULL, symbol text NOT NULL, "
    'timeframe text NOT NULL, "timestamp" timestamptz NOT NULL, old_open float8 NOT NULL, '
    "old_high float8 NOT NULL, old_low float8 NOT NULL, old_close float8 NOT NULL, "
    "old_volume bigint, old_source text NOT NULL, origin text NOT NULL, vendor text NOT NULL, "
    "kind text NOT NULL, request_id uuid)",
)


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    import psycopg

    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


@pytest.fixture
def conn():
    import psycopg

    if not _db_reachable():
        pytest.skip("local PostgreSQL not reachable")
    connection = psycopg.connect(_LIVE_DB_DSN)
    try:
        with connection.transaction(force_rollback=True):
            with connection.cursor() as cur:
                for statement in _SHADOW_DDL:
                    cur.execute(statement)
            yield connection
    finally:
        connection.close()


def _row(symbol, i, close=10.0, volume=100, served=SERVED, open_=9.0) -> RawRow:
    return RawRow(
        T0 + timedelta(minutes=5 * i),
        symbol,
        "5m",
        "massive",
        "sip_flat_agg",
        open_,
        11.0,
        8.5,
        close,
        volume,
        served,
    )


def _seed(conn, rows: list[RawRow], served_at=SERVED) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ohlcv_raw VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (r.timestamp, r.symbol, r.timeframe, r.vendor, r.kind, r.open, r.high, r.low)
                + (r.close, r.volume, served_at, OLD_REQUEST, OLD_LOAD)
                for r in rows
            ],
        )


def _ids(symbol: str) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid5(OLD_LOAD, symbol), uuid.uuid5(OLD_REQUEST, symbol)


def _capture(conn) -> tuple[list, list]:
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM ohlcv_raw ORDER BY symbol, "timestamp"')
        raw = [tuple(v.hex() if isinstance(v, float) else v for v in r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM ohlcv_revision")
        revision = sorted(
            (tuple(v.hex() if isinstance(v, float) else v for v in r) for r in cur.fetchall()),
            key=repr,
        )
    return raw, revision


def _row_path(conn, offers: list[RawRow]) -> tuple:
    counts = {}
    for symbol in sorted({r.symbol for r in offers}):
        rows = [r for r in offers if r.symbol == symbol]
        load_id, request_id = _ids(symbol)
        (delta,) = write_raw(
            conn,
            rows,
            load_id=load_id,
            request_id=request_id,
            answered_at=max(r.answered_at for r in rows),
            vendor_codes=VENDORS,
            kind_codes=KINDS,
            batch_rows=50_000,
            future_tolerance_s=3600,
            now=NOW,
        )
        counts[symbol] = [delta.new, delta.unchanged, delta.changed, delta.superseded]
    return counts, _capture(conn)


def _batch(offers: list[RawRow]):
    return build_raw_batch(
        timeframe="5m",
        vendor="massive",
        kind="sip_flat_agg",
        symbols=np.array([r.symbol for r in offers], dtype=object),
        ts_us=[datetime_to_us(r.timestamp) for r in offers],
        open=[r.open for r in offers],
        high=[r.high for r in offers],
        low=[r.low for r in offers],
        close=[r.close for r in offers],
        volume=[r.volume or 0 for r in offers],
        volume_null=[r.volume is None for r in offers],
        served_us=[datetime_to_us(r.answered_at) for r in offers],
        vendor_codes=VENDORS,
        kind_codes=KINDS,
        future_tolerance_s=3600,
        chunk_rows=10_000,
        now=NOW,
    )


def _bulk_path(conn, offers: list[RawRow]) -> tuple:
    batch = _batch(offers)
    symbols = [str(batch.symbols[b]) for b in batch.key_bounds()[:-1]]
    with conn.cursor() as cur:
        classified = stage_and_classify(cur, batch)
        write_classified(
            cur,
            classified,
            load_ids=[_ids(s)[0] for s in symbols],
            request_ids=[_ids(s)[1] for s in symbols],
        )
    counts = dict(zip(symbols, classified.counts.tolist(), strict=True))
    return counts, _capture(conn)


def _both(conn, stored: list[RawRow], offers: list[RawRow], *, served_at=SERVED):
    _seed(conn, stored, served_at)
    results = []
    for path in (_row_path, _bulk_path):
        with conn.transaction(force_rollback=True):
            results.append(path(conn, offers))
    row, bulk = results
    assert bulk == row
    return row


def test_new_rows_insert_with_their_own_serve_time(conn):
    offers = [_row("AAA", 0), _row("AAA", 1, served=SERVED + timedelta(hours=1)), _row("BBB", 0)]
    counts, (raw, revision) = _both(conn, [], offers)
    assert counts == {"AAA": [2, 0, 0, 0], "BBB": [1, 0, 0, 0]}
    assert len(raw) == 3 and revision == []


def test_equal_values_are_unchanged_including_signed_zero_and_null_volume(conn):
    stored = [_row("AAA", 0, close=-0.0), _row("AAA", 1, volume=None)]
    offers = [_row("AAA", 0, close=0.0), _row("AAA", 1, volume=None)]
    counts, (raw, revision) = _both(conn, stored, offers)
    assert counts == {"AAA": [0, 2, 0, 0]} and revision == []
    assert raw[0][8] == (-0.0).hex()  # the stored answer is kept


def test_a_changed_offer_answered_at_or_after_the_stored_one_replaces_it(conn):
    stored = [_row("AAA", i) for i in range(4)]
    offers = [
        _row("AAA", 0, close=10.01, served=SERVED),  # equal serve time replaces (>=)
        _row("AAA", 1, close=math.nextafter(10.0, 11.0), served=SERVED + timedelta(days=1)),
        _row("AAA", 2, volume=None, served=SERVED + timedelta(days=1)),  # NULL against 100
        _row("AAA", 3, open_=9.5, served=SERVED - timedelta(days=1)),  # older: superseded
    ]
    counts, (raw, revision) = _both(conn, stored, offers)
    assert counts == {"AAA": [0, 0, 3, 1]}
    origins = sorted(r[10] for r in revision)
    assert origins == ["raw", "raw", "raw", "superseded"]
    assert raw[3][5] == (9.0).hex()  # the superseded offer left raw alone


def test_a_stored_row_without_a_serve_time_is_always_replaced(conn):
    stored = [_row("AAA", 0)]
    counts, (raw, _revision) = _both(
        conn,
        stored,
        [_row("AAA", 0, close=12.0, served=SERVED - timedelta(days=9))],
        served_at=None,
    )
    assert counts == {"AAA": [0, 0, 1, 0]} and raw[0][8] == (12.0).hex()


def test_the_serve_time_split_is_row_by_row_within_one_series(conn):
    stored = [_row("AAA", i) for i in range(6)]
    offers = [
        _row("AAA", i, close=10.5, served=SERVED + timedelta(days=1 if i % 2 else -1))
        for i in range(6)
    ]
    counts, _ = _both(conn, stored, offers)
    assert counts == {"AAA": [0, 0, 3, 3]}


def test_a_stored_row_moved_under_the_lock_fails_loudly(conn):
    """A writer that bypassed the series lock moves the stored answer between classification and
    write: the guarded replacement then writes fewer rows than classified, and the transaction
    must fail rather than report a replacement that did not happen."""
    _seed(conn, [_row("AAA", 0)])
    batch = _batch([_row("AAA", 0, close=12.0, served=SERVED + timedelta(days=1))])
    with conn.transaction(force_rollback=True):
        with conn.cursor() as cur:
            classified = stage_and_classify(cur, batch)
            cur.execute("UPDATE ohlcv_raw SET served_at = %s", (SERVED + timedelta(days=5),))
            with pytest.raises(RuntimeError, match="moved under the series lock"):
                write_classified(cur, classified, load_ids=[OLD_LOAD], request_ids=[OLD_REQUEST])


def test_a_second_batch_in_one_transaction_starts_from_an_empty_stage(conn):
    offers = [_row("AAA", 0)]
    with conn.transaction(force_rollback=True):
        with conn.cursor() as cur:
            first = stage_and_classify(cur, _batch(offers))
            write_classified(cur, first, load_ids=[OLD_LOAD], request_ids=[OLD_REQUEST])
            second = stage_and_classify(cur, _batch(offers))
    assert first.counts.tolist() == [[1, 0, 0, 0]] and second.counts.tolist() == [[0, 1, 0, 0]]
