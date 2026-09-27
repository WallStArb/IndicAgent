#!/usr/bin/env python3
"""Measure write rates on a scratch compressed hypertable shaped like market_data_ohlcv
(phase 185 plan 01, RESEARCH assumptions A5 and A7).

Creates schema scratch_185 with a hypertable that carries market_data_ohlcv's exact
column list, PK, secondary indexes, 30-day chunks and the live table's compression
settings, fills it from market_data_ohlcv_tradeable for 20 symbols x ('1h', '5m', '1d')
over 2016-2025 capped at about 3M rows, compresses every chunk older than 30 days,
then measures each DML method with wall time, rows/s and hypertable_size before/after:

  a1. COPY insert of new rows (timestamps shifted, no conflicts) into compressed chunks
  a2. multi-row INSERT ... SELECT of the same shape
  b.  native upsert (INSERT ... ON CONFLICT DO UPDATE) of one full (symbol, '1h') segment
  c.  DELETE of one full (symbol, '1h') segment then COPY of the replacement rows, in one
      transaction, with iostat -x 1 5 sampled concurrently and pg_stat_activity wait
      events captured before and after
  d.  the same as (c) for one (symbol, '5m') segment
  e.  EXPLAIN (ANALYZE, BUFFERS) of the segment DELETE and of an insert into a compressed
      chunk (each executed then rolled back), plus per-step compressed-chunk counts as
      decompression evidence

It also checks whether a NOLOGIN role granted SELECT/INSERT/DELETE on the hypertable can
DML its compressed chunks. The role check's COPY shifts timestamps by +17 minutes: a
+60 minute shift lands every hourly bar exactly on its own next bar (guaranteed PK
self-conflict), and +30 would collide wherever a session mixes :00 and :30 stamps.

Every DML statement in this file names scratch_185.ohlcv only; the live table is touched
by SELECTs (through the tradeable view) and catalog reads. Run with --skip-teardown to
keep scratch_185 for manual EXPLAIN (ANALYZE, BUFFERS) probes; drop it afterwards.

Usage:
    .venv/bin/python scripts/ops/bars/ops_measure_ohlcv_write_rates.py [--skip-teardown]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import psycopg

from src.config.settings import Settings

_SCHEMA = "scratch_185"
_TABLE = "ohlcv"
_QUALIFIED = f"{_SCHEMA}.{_TABLE}"
_ROLE = "scratch_185_writer"

_COLS = '"timestamp", symbol, timeframe, open, high, low, close, volume, source, base'

_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "EEM",
    "EFA",
    "TLT",
    "GLD",
    "SLV",
    "XLF",
    "XLE",
    "XLK",
    "XLV",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "VTI",
    "VOO",
    "AGG",
    "LQD",
)

_FILL_START = "2016-01-01"
_FILL_END = "2026-01-01"


@dataclass
class Result:
    label: str
    rows: int
    seconds: float
    rows_per_s: float
    size_before: int
    size_after: int
    chunks_decompressed: int

    def line(self) -> str:
        delta = self.size_after - self.size_before
        return (
            f"{self.label}: rows={self.rows} seconds={self.seconds:.2f} "
            f"rows/s={self.rows_per_s:,.0f} "
            f"disk {self.size_before:,} -> {self.size_after:,} (delta {delta:+,}) "
            f"chunks_decompressed={self.chunks_decompressed}"
        )


def _size(cur: psycopg.Cursor) -> int:
    cur.execute("SELECT hypertable_size(%s::regclass)", (_QUALIFIED,))
    return int(cur.fetchone()[0])


def _chunk_status(cur: psycopg.Cursor) -> str:
    cur.execute(
        "SELECT is_compressed, count(*) FROM timescaledb_information.chunks "
        "WHERE hypertable_schema = %s AND hypertable_name = %s GROUP BY is_compressed",
        (_SCHEMA, _TABLE),
    )
    return "; ".join(f"is_compressed={r[0]}: {r[1]} chunks" for r in cur.fetchall())


def _compressed_count(cur: psycopg.Cursor) -> int:
    cur.execute(
        "SELECT count(*) FROM timescaledb_information.chunks "
        "WHERE hypertable_schema = %s AND hypertable_name = %s AND is_compressed",
        (_SCHEMA, _TABLE),
    )
    return int(cur.fetchone()[0])


def _timed(cur: psycopg.Cursor, label: str, rows: int, fn) -> Result:
    cur.connection.commit()
    before = _size(cur)
    chunks_before = _compressed_count(cur)
    t0 = time.perf_counter()
    fn()
    cur.connection.commit()
    seconds = time.perf_counter() - t0
    after = _size(cur)
    chunks_after = _compressed_count(cur)
    result = Result(
        label,
        rows,
        seconds,
        rows / seconds if seconds else 0.0,
        before,
        after,
        chunks_before - chunks_after,
    )
    print(result.line(), flush=True)
    return result


def _wait_event_snapshot(cur: psycopg.Cursor) -> str:
    cur.execute(
        "SELECT pid, wait_event_type, wait_event, left(query, 80) FROM pg_stat_activity "
        "WHERE datname = current_database() AND state = 'active' AND pid <> pg_backend_pid()"
    )
    rows = cur.fetchall()
    if not rows:
        return "no other active backends"
    return "; ".join(f"pid={r[0]} wait={r[1]}/{r[2]} q={r[3]}" for r in rows)


def setup(cur: psycopg.Cursor) -> None:
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {_QUALIFIED} (
            "timestamp" timestamptz NOT NULL,
            symbol text NOT NULL,
            timeframe text NOT NULL,
            open double precision NOT NULL,
            high double precision NOT NULL,
            low double precision NOT NULL,
            close double precision NOT NULL,
            volume bigint NOT NULL,
            source text,
            base text,
            price_sanity_status text,
            CONSTRAINT {_TABLE}_pkey PRIMARY KEY ("timestamp", symbol, timeframe)
        )
        """)
    cur.connection.commit()
    cur.execute(f"""
        SELECT create_hypertable({_QUALIFIED!r}, 'timestamp',
            chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE)
        """)
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_symbol_tf_time "
        f'ON {_QUALIFIED} (symbol, timeframe, "timestamp" DESC)'
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_price_sanity_unaudited "
        f'ON {_QUALIFIED} (symbol, timeframe, "timestamp") '
        f"WHERE price_sanity_status IS NULL"
    )
    cur.connection.commit()
    cur.execute("""
        SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc,
               orderby_nullsfirst
        FROM timescaledb_information.compression_settings
        WHERE hypertable_schema = 'public' AND hypertable_name = 'market_data_ohlcv'
        """)
    rows = cur.fetchall()
    segmentby = ", ".join(f'"{r[0]}"' for r in rows if r[1] is not None)
    orderby_rows = sorted((r[2], r[0], r[3], r[4]) for r in rows if r[2] is not None)
    orderby = ", ".join(
        f'"{name}"' + (" ASC" if asc else " DESC") + (" NULLS FIRST" if nulls_first else "")
        for _, name, asc, nulls_first in orderby_rows
    )
    cur.execute(f"""
        ALTER TABLE {_QUALIFIED} SET (
            timescaledb.compress = TRUE,
            timescaledb.compress_segmentby = '{segmentby}',
            timescaledb.compress_orderby = '{orderby}'
        )
        """)
    cur.connection.commit()
    print(f"compression settings: segmentby=({segmentby}) orderby=({orderby})", flush=True)


def fill(cur: psycopg.Cursor, row_cap: int) -> int:
    symbols = list(_SYMBOLS)
    cur.execute(
        f"""
        INSERT INTO {_QUALIFIED}
        SELECT "timestamp", symbol, timeframe, open, high, low, close,
               COALESCE(volume, 0), source, base, price_sanity_status
        FROM market_data_ohlcv_tradeable
        WHERE symbol = ANY(%s) AND timeframe IN ('1d', '1h')
          AND "timestamp" >= %s AND "timestamp" < %s
        """,
        (symbols, _FILL_START, _FILL_END),
    )
    n_base = cur.rowcount
    cur.connection.commit()
    print(f"filled 1d+1h for {len(symbols)} symbols: {n_base} rows", flush=True)

    n_5m = 0
    for symbol in symbols:
        if n_base + n_5m >= row_cap:
            break
        cur.execute(
            f"""
            INSERT INTO {_QUALIFIED}
            SELECT "timestamp", symbol, timeframe, open, high, low, close,
                   COALESCE(volume, 0), source, base, price_sanity_status
            FROM market_data_ohlcv_tradeable
            WHERE symbol = %s AND timeframe = '5m'
              AND "timestamp" >= %s AND "timestamp" < %s
            """,
            (symbol, _FILL_START, _FILL_END),
        )
        n_5m += cur.rowcount
        cur.connection.commit()
        print(f"  5m {symbol}: cumulative {n_base + n_5m}", flush=True)
        if n_base + n_5m >= row_cap:
            break
    total = n_base + n_5m
    print(f"fill complete: {total} rows", flush=True)
    return total


def compress_old_chunks(cur: psycopg.Cursor) -> None:
    t0 = time.perf_counter()
    # _SCHEMA/_TABLE are compile-time constants of this script, safe to inline
    # (psycopg's client-side placeholder parser rejects %I).
    cur.execute(f"""
        SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass)
        FROM timescaledb_information.chunks
        WHERE hypertable_schema = '{_SCHEMA}' AND hypertable_name = '{_TABLE}'
          AND NOT is_compressed
          AND range_end < now() - INTERVAL '30 days'
        """)
    n = cur.rowcount
    cur.connection.commit()
    print(f"compressed {n} chunks in {time.perf_counter() - t0:.1f}s", flush=True)
    print(f"chunk status: {_chunk_status(cur)}", flush=True)


def _segment_rows(cur: psycopg.Cursor, symbol: str, tf: str) -> list[tuple]:
    cur.execute(
        f"SELECT {_COLS} FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = %s "
        'ORDER BY "timestamp"',
        (symbol, tf),
    )
    return cur.fetchall()


def _copy_rows(cur: psycopg.Cursor, rows: list[tuple], shift_minutes: int) -> int:
    """COPY rows in, with every timestamp shifted by shift_minutes (0 = verbatim)."""
    with cur.copy(
        f"COPY {_QUALIFIED} ({_COLS}) FROM STDIN WITH (FORMAT TEXT, DELIMITER '|')"
    ) as copy:
        for row in rows:
            shifted = row[0] + timedelta(minutes=shift_minutes)
            fields = [str(shifted)] + ["\\N" if v is None else str(v) for v in row[1:]]
            copy.write("|".join(fields) + "\n")
    return len(rows)


def measure(cur: psycopg.Cursor, symbols: list[str]) -> tuple[list[Result], dict]:
    results: list[Result] = []
    extras: dict[str, str] = {}

    # Distinct symbols keep each measurement independent of the previous ones.
    seg_copy_ins, seg_multi_ins, seg_upsert, seg_del_1h, seg_del_5m = symbols[:5]

    # (a1) plain INSERT via COPY into compressed chunks: one full 1h segment, +30 min.
    rows_a1 = _segment_rows(cur, seg_copy_ins, "1h")

    def _copy_insert_a1() -> None:
        _copy_rows(cur, rows_a1, 30)

    results.append(
        _timed(
            cur,
            f"a1 COPY insert into compressed chunks ({seg_copy_ins} 1h segment)",
            len(rows_a1),
            _copy_insert_a1,
        )
    )

    # (a2) plain INSERT via multi-row INSERT ... SELECT, +45 min, another symbol.
    rows_a2 = _segment_rows(cur, seg_multi_ins, "1h")

    def _insert_select_a2() -> None:
        cur.execute(
            f"""
            INSERT INTO {_QUALIFIED}
            SELECT "timestamp" + INTERVAL '45 minutes', symbol, timeframe, open, high,
                   low, close, volume, source, base, price_sanity_status
            FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '1h'
            """,
            (seg_multi_ins,),
        )

    results.append(
        _timed(
            cur,
            f"a2 multi-row INSERT ... SELECT into compressed chunks ({seg_multi_ins} 1h segment)",
            len(rows_a2),
            _insert_select_a2,
        )
    )

    # (b) native upsert of one full 1h segment (rows conflict with themselves).
    def _upsert_b() -> None:
        cur.execute(
            f"""
            INSERT INTO {_QUALIFIED}
            SELECT {_COLS} FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '1h'
            ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume,
                source = EXCLUDED.source, base = EXCLUDED.base
            """,
            (seg_upsert,),
        )

    rows_b = _segment_rows(cur, seg_upsert, "1h")
    results.append(
        _timed(cur, f"b native upsert one full 1h segment ({seg_upsert})", len(rows_b), _upsert_b)
    )

    # (c) DELETE one full 1h segment then COPY the replacement rows, one transaction,
    # with iostat sampled concurrently and wait events captured around it.
    rows_c = _segment_rows(cur, seg_del_1h, "1h")

    def _delete_then_copy_1h() -> None:
        cur.execute(
            f"DELETE FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '1h'",
            (seg_del_1h,),
        )
        _copy_rows(cur, rows_c, 0)
        cur.connection.commit()

    extras["wait_before_c"] = _wait_event_snapshot(cur)
    iostat_proc = subprocess.Popen(
        ["iostat", "-x", "1", "5"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    results.append(
        _timed(
            cur,
            f"c DELETE + COPY reinsert one full 1h segment ({seg_del_1h})",
            len(rows_c),
            _delete_then_copy_1h,
        )
    )
    out, err = iostat_proc.communicate(timeout=30)
    extras["wait_after_c"] = _wait_event_snapshot(cur)
    extras["iostat_c"] = out if not err.strip() else f"{out}\niostat stderr: {err}"

    # (d) same for one full 5m segment.
    rows_d = _segment_rows(cur, seg_del_5m, "5m")

    def _delete_then_copy_5m() -> None:
        cur.execute(
            f"DELETE FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '5m'",
            (seg_del_5m,),
        )
        _copy_rows(cur, rows_d, 0)
        cur.connection.commit()

    results.append(
        _timed(
            cur,
            f"d DELETE + COPY reinsert one full 5m segment ({seg_del_5m})",
            len(rows_d),
            _delete_then_copy_5m,
        )
    )
    return results, extras


def role_check(cur: psycopg.Cursor, symbols: list[str]) -> dict:
    cur.connection.commit()
    cur.execute(f"DROP ROLE IF EXISTS {_ROLE}")
    cur.execute(f"CREATE ROLE {_ROLE} NOLOGIN")
    cur.execute(f"GRANT USAGE ON SCHEMA {_SCHEMA} TO {_ROLE}")
    cur.execute(f"GRANT SELECT, INSERT, DELETE ON {_QUALIFIED} TO {_ROLE}")
    cur.connection.commit()
    outcome = {
        "role": _ROLE,
        "grants": f"USAGE on {_SCHEMA}; SELECT, INSERT, DELETE on {_QUALIFIED}",
    }
    rows = _segment_rows(cur, symbols[5], "1h")

    def _role_dml() -> None:
        with cur.connection.transaction():
            cur.execute(f"SET LOCAL ROLE {_ROLE}")
            # +17 min: +60 lands each 1h bar on its own next bar (PK self-conflict);
            # +30 collides on sessions that mix :00 and :30 stamps.
            _copy_rows(cur, rows, 17)
            cur.execute(
                f"DELETE FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '1h'",
                (symbols[6],),
            )

    try:
        _role_dml()
        outcome["result"] = "SUCCEEDED"
        outcome["detail"] = (
            f"role copied {len(rows)} rows (+17 min shift) into compressed chunks and "
            f"deleted one full 1h segment ({symbols[6]})"
        )
    except psycopg.Error as error:
        outcome["result"] = "REFUSED"
        outcome["detail"] = f"{type(error).__name__}: {str(error).splitlines()[0][:400]}"
    finally:
        cur.connection.rollback()
        cur.connection.commit()
        # The role is a grantee of privileges on the table, which DROP ROLE refuses
        # to cascade; DROP OWNED revokes those grants first.
        cur.execute(f"DROP OWNED BY {_ROLE}")
        cur.execute(f"DROP ROLE IF EXISTS {_ROLE}")
        cur.connection.commit()
    return outcome


def explain_samples(cur: psycopg.Cursor, symbols: list[str]) -> dict[str, str]:
    """EXPLAIN (ANALYZE, BUFFERS) evidence for item (e); each statement executes then rolls back."""
    samples: dict[str, str] = {}
    cur.connection.commit()
    cur.execute(
        f"EXPLAIN (ANALYZE, BUFFERS) DELETE FROM {_QUALIFIED} "
        "WHERE symbol = %s AND timeframe = '1h'",
        (symbols[7],),
    )
    samples["delete_1h_segment"] = "\n".join(str(r[0]) for r in cur.fetchall())
    cur.connection.rollback()
    cur.connection.commit()
    cur.execute(
        f"""
        EXPLAIN (ANALYZE, BUFFERS) INSERT INTO {_QUALIFIED}
        SELECT "timestamp" + INTERVAL '17 minutes', symbol, timeframe, open, high, low,
               close, volume, source, base, price_sanity_status
        FROM {_QUALIFIED} WHERE symbol = %s AND timeframe = '1h'
        """,
        (symbols[8],),
    )
    samples["insert_into_compressed"] = "\n".join(str(r[0]) for r in cur.fetchall())
    cur.connection.rollback()
    return samples


def teardown(cur: psycopg.Cursor) -> None:
    cur.connection.commit()
    cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    cur.connection.commit()
    # role_check's finally block may already have dropped the role; DROP OWNED BY
    # has no IF EXISTS form, so guard on pg_roles first.
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (_ROLE,))
    if cur.fetchone() is not None:
        cur.execute(f"DROP OWNED BY {_ROLE}")
        cur.execute(f"DROP ROLE IF EXISTS {_ROLE}")
        cur.connection.commit()
    print(f"dropped {_SCHEMA} and {_ROLE}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--row-cap", type=int, default=3_000_000)
    parser.add_argument(
        "--skip-teardown",
        action="store_true",
        help="Leave scratch_185 in place for manual EXPLAIN probes (drop it afterwards).",
    )
    args = parser.parse_args()

    settings = Settings()
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            try:
                setup(cur)
                total = fill(cur, args.row_cap)
                compress_old_chunks(cur)
                symbols = list(_SYMBOLS)
                for symbol in symbols[:7]:
                    cur.execute(
                        f"SELECT timeframe, count(*) FROM {_QUALIFIED} "
                        "WHERE symbol = %s GROUP BY timeframe",
                        (symbol,),
                    )
                    print(f"segment sizes {symbol}: {cur.fetchall()}", flush=True)

                results, extras = measure(cur, symbols)
                role_outcome = role_check(cur, symbols)
                explains = explain_samples(cur, symbols)

                print("\nrole check:", flush=True)
                for key, value in role_outcome.items():
                    print(f"  {key}: {value}", flush=True)
                print(f"\ntotal rows filled: {total}", flush=True)
                print("\nresults summary:", flush=True)
                for r in results:
                    print(f"  {r.line()}", flush=True)
                print("\nwait events around (c):", flush=True)
                print(f"  before: {extras['wait_before_c']}", flush=True)
                print(f"  after: {extras['wait_after_c']}", flush=True)
                print("\niostat -x 1 5 sampled during the (c) delete+reinsert:", flush=True)
                print(extras["iostat_c"], flush=True)
                print(
                    "\nEXPLAIN (ANALYZE, BUFFERS) samples (executed and rolled back):", flush=True
                )
                for label, plan in explains.items():
                    print(f"  --- {label} ---", flush=True)
                    for line in plan.splitlines():
                        print(f"    {line}", flush=True)
            finally:
                if not args.skip_teardown:
                    teardown(cur)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
