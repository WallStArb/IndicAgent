"""Scratch-database rehearsal of the market_data_ohlcv real-rows swap (todo 462 step 6, plan 185-25).

Creates its own database (`scratch_real_rows_swap_<pid>`), builds a market_data_ohlcv shaped like
the live one (mixed 30- and 90-day chunks, compressed and uncompressed, the live compression
settings, policy, grants, storage options and the three dependent views with their live
definitions), seeds synthetic_fill placeholders between real rows, applies migration 439 as
written, and walks every step of scripts/ops/bars/ops_real_rows_swap.py through its CLI: the
refusals, the copy and its restart, a forced digest mismatch and a forced count mismatch (both
abort with the original untouched), a write between the verify and the lock (aborts), the swap,
the rollback, the swap again, the drop and the VACUUM. Drops the database at the end.

Never touches the live database. Self-contained, so run it without the integration conftest
(which rebuilds indicagent_test first):

    .venv/bin/python -m pytest --noconftest -s tests/integration/test_ops_real_rows_swap_scratch.py

SCRATCH_SWAP_SYMBOLS scales the fixture (default 4 symbols; 60 gives a few million rows, for
timing).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

from scripts.ops.bars import ops_real_rows_swap as swap

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_REPO = Path(__file__).resolve().parents[2]
_MIGRATION = _REPO / "production" / "migrations" / "439_market_data_ohlcv_real_rows_swap.sql"
_ADMIN_DSN = os.environ.get(
    "SCRATCH_SWAP_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5432/postgres"
)
_SCRATCH = f"scratch_real_rows_swap_{os.getpid()}"
_N_SYMBOLS = int(os.environ.get("SCRATCH_SWAP_SYMBOLS", "4"))

# The live table and its views as of 2026-10-06 (read from the live catalog, written out here so
# the rehearsal never connects to the live database).
_FIXTURE_DDL = """
CREATE EXTENSION IF NOT EXISTS timescaledb;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END $$;

CREATE TABLE config_schema (config_key text PRIMARY KEY, value_type text NOT NULL,
    default_value text, min_value double precision, max_value double precision,
    allowed_values text[], is_secret boolean DEFAULT false, version integer DEFAULT 1,
    description text, created_at timestamptz DEFAULT now());
CREATE TABLE config_state (config_key text PRIMARY KEY, config_value text NOT NULL,
    version integer NOT NULL, updated_at timestamptz DEFAULT now());
CREATE TABLE config_history (timestamp timestamptz NOT NULL, config_key text NOT NULL,
    version integer NOT NULL, config_value text NOT NULL, changed_by text NOT NULL, reason text);
CREATE TABLE integrity_monitor (id bigserial PRIMARY KEY, monitor_type text NOT NULL,
    subject text, metric_name text NOT NULL, metric_value double precision,
    threshold_value double precision, passed boolean NOT NULL,
    training_window_end timestamptz, evaluated_at timestamptz NOT NULL DEFAULT now());
INSERT INTO integrity_monitor (monitor_type, subject, metric_name, metric_value, passed)
VALUES ('bar_reconciliation', 'derived tf=15m', 'masked_slots_derived_symbols', 0, true),
       ('bar_reconciliation', 'derived tf=1h', 'masked_slots_derived_symbols', 0, true);
CREATE TABLE bar_quality_flag (symbol text NOT NULL, timeframe text NOT NULL,
    "timestamp" timestamptz NOT NULL, rule text NOT NULL, rule_version text NOT NULL,
    fields text[] NOT NULL DEFAULT '{}', quarantine boolean NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}', flagged_at timestamptz NOT NULL DEFAULT now(),
    batch_id uuid);

CREATE TABLE market_data_ohlcv (
    "timestamp" timestamptz NOT NULL, symbol text NOT NULL, timeframe text NOT NULL,
    open double precision NOT NULL, high double precision NOT NULL,
    low double precision NOT NULL, close double precision NOT NULL, volume bigint NOT NULL,
    source text, base text, price_sanity_status text
) WITH (autovacuum_vacuum_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02);
SELECT create_hypertable('market_data_ohlcv', by_range('timestamp', INTERVAL '30 days'),
                         create_default_indexes => false);
CREATE UNIQUE INDEX market_data_ohlcv_pkey_idx ON market_data_ohlcv ("timestamp", symbol, timeframe);
CREATE INDEX idx_ohlcv_symbol_tf_time ON market_data_ohlcv (symbol, timeframe, "timestamp" DESC);
ALTER TABLE market_data_ohlcv SET (timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = '"timestamp" ASC');
GRANT SELECT, INSERT, UPDATE, DELETE ON market_data_ohlcv TO bar_derivation_writer;

CREATE VIEW market_data_5m AS
 SELECT "timestamp", symbol, base, timeframe, open, high, low, close, volume, source
   FROM market_data_ohlcv WHERE timeframe = '5m'::text;
CREATE VIEW market_data_ohlcv_scrub_input AS
 SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, source
   FROM market_data_ohlcv WHERE volume > 0;
CREATE VIEW market_data_ohlcv_tradeable AS
 SELECT "timestamp", symbol, timeframe, open, high, low, close,
        CASE WHEN source = 'ibkr_venue'::text THEN NULL::bigint ELSE volume END AS volume,
        source, base, price_sanity_status
   FROM market_data_ohlcv
  WHERE volume > 0 AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'::text
    AND NOT (EXISTS (SELECT 1 FROM bar_quality_flag q
                      WHERE q.quarantine AND q.symbol = market_data_ohlcv.symbol
                        AND q.timeframe = market_data_ohlcv.timeframe
                        AND q."timestamp" = market_data_ohlcv."timestamp"));
GRANT SELECT ON market_data_ohlcv_scrub_input, market_data_ohlcv_tradeable TO bar_derivation_writer;
"""

# Rows: per symbol, real bars inside the session and synthetic_fill placeholders (volume 0)
# outside it, at five timeframes. ZZZ0 carries real zero-volume rows and NULL-source rows (both
# real rows a careless filter would drop). Generated relative to now() so the newest window stays
# uncompressed, like the live table's.
_ROWS_SQL = """
INSERT INTO market_data_ohlcv
SELECT ts, sym, tf, 100 + h, 101 + h, 99 + h, 100.5 + h,
       CASE WHEN synthetic THEN 0 ELSE 1000 + (h * 10)::bigint END,
       CASE WHEN synthetic THEN 'synthetic_fill'
            WHEN tf = '1d' THEN 'tradier'
            WHEN tf IN ('15m', '1h') THEN 'derived_5m' ELSE 'ibkr_named' END,
       sym,
       CASE WHEN NOT synthetic AND mod((h * 1000)::int, 97) = 0 THEN 'confirmed_corrupt'
            WHEN NOT synthetic AND mod((h * 1000)::int, 13) = 0 THEN 'ok' END
FROM (
    SELECT s.sym, g.tf, g.ts,
           mod(extract(epoch FROM g.ts)::bigint, 1000) / 1000.0 + s.i AS h,
           CASE WHEN g.tf = '1d' THEN extract(dow FROM g.ts) IN (0, 6)
                ELSE (g.ts AT TIME ZONE 'UTC')::time NOT BETWEEN '14:30' AND '20:55' END
               AS synthetic
    FROM (SELECT i, 'S' || lpad(i::text, 3, '0') AS sym FROM generate_series(1, %(n)s) i) s
    CROSS JOIN LATERAL (
        SELECT '1d' AS tf, t AS ts FROM generate_series(
            date_trunc('day', now()) - interval '700 days', date_trunc('day', now()), '1 day') t
        UNION ALL SELECT '1h', t FROM generate_series(
            date_trunc('hour', now()) - interval '400 days', date_trunc('hour', now()), '1 hour') t
        UNION ALL SELECT '15m', t FROM generate_series(
            date_trunc('hour', now()) - interval '300 days', date_trunc('hour', now()), '15 min') t
        UNION ALL SELECT '5m', t FROM generate_series(
            date_trunc('hour', now()) - interval '200 days', date_trunc('hour', now()), '5 min') t
        UNION ALL SELECT '1m', t FROM generate_series(
            date_trunc('hour', now()) - interval '20 days', date_trunc('hour', now()), '1 min') t
    ) g
) x
WHERE x.ts < %(before)s
"""


def _psql_file(dsn: str, path: Path) -> str:
    out = subprocess.run(
        ["psql", dsn, "-X", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout + out.stderr


def _cli(capsys, dsn: str, tmp_path: Path, *args: str) -> tuple[int, dict]:
    code = swap.main([*args, "--dsn", dsn, "--data-path", str(tmp_path)])
    out = capsys.readouterr().out
    return code, json.loads(out)


def _table_digest(conn, table: str) -> tuple[int, int, str]:
    """(oid, rows, digest) over every row, placeholders included: the original is untouched only
    if all three hold."""
    oid = conn.execute("SELECT %s::regclass::oid", (table,)).fetchone()[0]
    n, digest = conn.execute(
        f"""SELECT count(*), md5(string_agg(ROW("timestamp", symbol, timeframe, open, high, low,
            close, volume, source, base, price_sanity_status)::text, E'\\n'
            ORDER BY symbol, timeframe, "timestamp")) FROM {table}"""
    ).fetchone()
    return int(oid), int(n), str(digest)


def _view_owner_table(conn, view: str) -> int:
    return conn.execute(
        """SELECT DISTINCT d.refobjid::oid FROM pg_rewrite r JOIN pg_depend d ON d.objid = r.oid
           JOIN pg_class t ON t.oid = d.refobjid
           WHERE r.ev_class = %s::regclass AND t.relkind = 'r' AND t.relname LIKE 'market_data_ohlcv%%'""",
        (view,),
    ).fetchone()[0]


def _compressed_chunk(conn, table: str) -> str:
    return conn.execute(
        """SELECT format('%%I.%%I', chunk_schema, chunk_name) FROM timescaledb_information.chunks
           WHERE hypertable_name = %s AND is_compressed ORDER BY range_start LIMIT 1""",
        (table,),
    ).fetchone()[0]


@pytest.fixture(scope="module")
def scratch_dsn():
    try:
        admin = psycopg.connect(_ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        pytest.skip(f"no PostgreSQL for the scratch rehearsal: {error}")
    admin.execute(f'CREATE DATABASE "{_SCRATCH}"')
    dsn = _ADMIN_DSN.rsplit("/", 1)[0] + "/" + _SCRATCH
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(_FIXTURE_DDL)
            split = conn.execute(
                "SELECT date_trunc('day', now()) - interval '120 days'"
            ).fetchone()[0]
            conn.execute(_ROWS_SQL, {"n": _N_SYMBOLS, "before": split})
            conn.execute("SELECT set_chunk_time_interval('market_data_ohlcv', INTERVAL '90 days')")
            conn.execute(
                _ROWS_SQL.replace("WHERE x.ts < %(before)s", "WHERE x.ts >= %(before)s"),
                {"n": _N_SYMBOLS, "before": split},
            )
            # Real rows a careless filter would drop: zero-volume provider bars, NULL source.
            conn.execute(
                """INSERT INTO market_data_ohlcv VALUES
                   (now() - interval '50 days', 'ZZZ0', '1d', 1, 1, 1, 1, 0, 'ibkr_named', 'ZZZ0', NULL),
                   (now() - interval '400 days', 'ZZZ0', '1d', 2, 2, 2, 2, 5, NULL, 'ZZZ0', NULL)"""
            )
            conn.execute(
                """INSERT INTO bar_quality_flag (symbol, timeframe, "timestamp", rule, rule_version, quarantine)
                   SELECT symbol, timeframe, "timestamp", 'spike', 'v1', true FROM market_data_ohlcv
                   WHERE source = 'ibkr_named' AND timeframe = '5m' ORDER BY "timestamp" LIMIT 7"""
            )
            conn.execute("""SELECT compress_chunk(c) FROM show_chunks('market_data_ohlcv',
                   older_than => now() - interval '30 days') c""")
            conn.execute(
                """SELECT add_compression_policy('market_data_ohlcv', compress_after => INTERVAL '30 days',
                   schedule_interval => INTERVAL '12 hours', initial_start => now() + interval '7 days')"""
            )
        yield dsn
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{_SCRATCH}" WITH (FORCE)')
        admin.close()


def test_rehearsal(scratch_dsn, capsys, tmp_path, monkeypatch):
    dsn = scratch_dsn
    summary: dict = {}
    conn = psycopg.connect(dsn, autocommit=True)

    # --- migration 439 as written ---------------------------------------------------------------
    _psql_file(dsn, _MIGRATION)
    assert swap.load_state(conn) == swap.PRE
    shape_diff = swap.shape_differences(
        swap.load_shape(conn, "market_data_ohlcv"), swap.load_shape(conn, "market_data_ohlcv_new")
    )
    assert shape_diff == [], shape_diff
    _psql_file(dsn, _MIGRATION)  # idempotent
    assert swap.load_state(conn) == swap.PRE
    original = _table_digest(conn, "market_data_ohlcv")
    summary["original_rows"] = original[1]

    # --- dry run ---------------------------------------------------------------------------------
    code, report = _cli(capsys, dsn, tmp_path)
    assert code == swap.EXIT_BLOCKED
    assert report["writers"]["host_checks"] is False
    assert all("placeholder_coverage" in b for b in report["blockers"]), report["blockers"]
    summary["dry_run_totals"] = report["totals"]

    # --- refusals: placeholder coverage not accepted; a fetcher lock holder in this database ------
    code, report = _cli(capsys, dsn, tmp_path, "--copy")
    assert code == swap.EXIT_BLOCKED and report["result"] == "refused: nothing copied"
    assert conn.execute("SELECT count(*) FROM market_data_ohlcv_new").fetchone()[0] == 0
    holder = psycopg.connect(
        dsn, autocommit=True, application_name="lock:ibkr_history_fetcher:test"
    )
    classid, objid = swap.advisory_key_parts("ibkr_history_fetcher")
    key = (classid << 32) | objid
    holder.execute("SELECT pg_advisory_lock(%s)", (key - (1 << 64) if key >= 1 << 63 else key,))
    code, report = _cli(capsys, dsn, tmp_path, "--copy", "--accept-placeholder-coverage")
    assert code == swap.EXIT_BLOCKED
    assert any("lock held" in b for b in report["gates"]["blockers"])
    holder.close()

    # --- copy, then restart --------------------------------------------------------------------
    t0 = time.monotonic()
    code, report = _cli(capsys, dsn, tmp_path, "--copy", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK, report
    copy = report["copy"]
    summary["copy"] = {
        k: copy[k] for k in ("windows", "windows_copied", "rows_copied", "copy_seconds")
    }
    summary["copy"]["wall_seconds"] = round(time.monotonic() - t0, 1)
    assert copy["count_differences"] == []
    assert copy["rebuilt_by_timeframe"] == copy["original_real_by_timeframe"]
    assert _table_digest(conn, "market_data_ohlcv") == original

    code, report = _cli(capsys, dsn, tmp_path, "--copy", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK
    assert report["copy"]["windows_done_earlier"] == copy["windows_copied"] - sum(
        1 for e in copy["log"] if e.get("status") == "copied" and not e["compressed"]
    )
    summary["restart_recopied_windows"] = report["copy"]["windows_copied"]

    # a crash between a window's copy and its compression: the chunk is complete but uncompressed
    chunk = _compressed_chunk(conn, "market_data_ohlcv_new")
    conn.execute("SELECT decompress_chunk(%s::regclass)", (chunk,))
    conn.execute(
        f"DELETE FROM {chunk} WHERE ctid IN (SELECT ctid FROM {chunk} LIMIT 5)"
    )  # and partial
    code, report = _cli(capsys, dsn, tmp_path, "--copy", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK and report["copy"]["count_differences"] == []

    # --- forced digest mismatch: swap aborts, original untouched ------------------------------
    chunk = _compressed_chunk(conn, "market_data_ohlcv_new")
    conn.execute("SELECT decompress_chunk(%s::regclass)", (chunk,))
    conn.execute(
        f"UPDATE {chunk} SET close = close + 0.01 WHERE ctid = (SELECT ctid FROM {chunk} LIMIT 1)"
    )
    conn.execute("SELECT compress_chunk(%s::regclass)", (chunk,))
    views_before = {
        v: _view_owner_table(conn, v)
        for v in ("market_data_5m", "market_data_ohlcv_scrub_input", "market_data_ohlcv_tradeable")
    }
    code, report = _cli(capsys, dsn, tmp_path, "--swap", "--accept-placeholder-coverage")
    assert code == swap.EXIT_BLOCKED
    assert report["result"] == "aborted at verify: original untouched"
    assert len(report["verify"]["digest_mismatch"]) == 1 and not report["verify"]["count_mismatch"]
    summary["forced_digest_mismatch"] = report["verify"]["digest_mismatch"]
    assert swap.load_state(conn) == swap.PRE
    assert _table_digest(conn, "market_data_ohlcv") == original
    assert {v: _view_owner_table(conn, v) for v in views_before} == views_before
    assert views_before["market_data_ohlcv_tradeable"] == original[0]

    # --- forced count mismatch ------------------------------------------------------------------
    conn.execute("SELECT decompress_chunk(%s::regclass)", (chunk,))  # copy repairs it
    conn.execute(f"DELETE FROM {chunk} WHERE ctid = (SELECT ctid FROM {chunk} LIMIT 1)")
    code, report = _cli(capsys, dsn, tmp_path, "--swap", "--accept-placeholder-coverage")
    assert code == swap.EXIT_BLOCKED and len(report["verify"]["count_mismatch"]) == 1
    summary["forced_count_mismatch"] = report["verify"]["count_mismatch"]
    assert _table_digest(conn, "market_data_ohlcv") == original
    code, report = _cli(capsys, dsn, tmp_path, "--copy", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK and report["copy"]["windows_copied"] >= 1

    # --- a write between the verify and the lock aborts the swap -------------------------------
    real_verify = swap.verify

    def verify_then_write(c, host_checks=True):
        result = real_verify(c, host_checks)
        with psycopg.connect(dsn, autocommit=True) as writer:
            writer.execute("""UPDATE market_data_ohlcv SET price_sanity_status = 'injected'
                   WHERE symbol = 'ZZZ0' AND volume = 0""")
        return result

    monkeypatch.setattr(swap, "verify", verify_then_write)
    code, report = _cli(capsys, dsn, tmp_path, "--swap", "--accept-placeholder-coverage")
    monkeypatch.setattr(swap, "verify", real_verify)
    assert code == swap.EXIT_BLOCKED and "written after the verify began" in report["aborted"]
    summary["write_after_verify"] = report["aborted"]
    assert swap.load_state(conn) == swap.PRE
    conn.execute(
        "UPDATE market_data_ohlcv SET price_sanity_status = NULL WHERE symbol = 'ZZZ0' AND volume = 0"
    )
    assert _table_digest(conn, "market_data_ohlcv")[1:] == original[1:]

    # --- the swap ------------------------------------------------------------------------------
    tradeable_before = dict(
        conn.execute(
            "SELECT timeframe, count(*) FROM market_data_ohlcv_tradeable GROUP BY 1"
        ).fetchall()
    )
    code, report = _cli(capsys, dsn, tmp_path, "--swap", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK, (
        report.get("result"),
        report.get("post_check", {}).get("blockers"),
    )
    summary["swap"] = {
        "verify": {
            k: report["verify"][k] for k in ("symbols", "compared", "real_rows_compared", "seconds")
        },
        "lock_seconds": report["lock_seconds"],
        "exchange": report["exchange"],
        "post_check_views": report["post_check"]["views"],
        "smoke": report["post_check"]["smoke"],
    }
    assert swap.load_state(conn) == swap.SWAPPED
    assert _table_digest(conn, "market_data_ohlcv_old") == original  # kept, untouched
    rebuilt_oid = conn.execute("SELECT 'market_data_ohlcv'::regclass::oid").fetchone()[0]
    assert all(_view_owner_table(conn, v) == rebuilt_oid for v in views_before)
    assert (
        conn.execute(
            "SELECT count(*) FROM market_data_ohlcv WHERE source = 'synthetic_fill'"
        ).fetchone()[0]
        == 0
    )
    tradeable_after = dict(
        conn.execute(
            "SELECT timeframe, count(*) FROM market_data_ohlcv_tradeable GROUP BY 1"
        ).fetchall()
    )
    assert tradeable_after == tradeable_before
    summary["tradeable_by_timeframe"] = tradeable_after
    acl = conn.execute(
        "SELECT relname, relacl::text FROM pg_class WHERE relname LIKE 'market_data_ohlcv%%' AND relkind = 'v' ORDER BY 1"
    ).fetchall()
    assert all("bar_derivation_writer=r" in a for _, a in acl), acl  # view grants survived
    indexes = sorted(
        r[0]
        for r in conn.execute(
            "SELECT indexrelid::regclass::text FROM pg_index WHERE indrelid = 'market_data_ohlcv'::regclass"
        )
    )
    assert indexes == ["idx_ohlcv_symbol_tf_time", "market_data_ohlcv_pkey_idx"]
    # the renamed indexes still serve writes: insert into a compressed window and recompress
    conn.execute(
        """INSERT INTO market_data_ohlcv VALUES (now() - interval '200 days' + interval '3 minutes',
           'NEW1', '5m', 1, 1, 1, 1, 1, 'ibkr_named', 'NEW1', NULL)"""
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            """INSERT INTO market_data_ohlcv SELECT * FROM market_data_ohlcv WHERE symbol = 'NEW1'"""
        )
    conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = 'NEW1'")

    code, report = _cli(capsys, dsn, tmp_path, "--post-check")
    assert code == swap.EXIT_OK, report["blockers"]

    # --- rollback, then the swap again ------------------------------------------------------------
    code, report = _cli(capsys, dsn, tmp_path, "--rollback")
    assert code == swap.EXIT_OK and report["state"] == swap.PRE
    assert _table_digest(conn, "market_data_ohlcv") == original
    assert all(_view_owner_table(conn, v) == original[0] for v in views_before)
    policies = {
        t: swap.load_policies(conn, t) for t in ("market_data_ohlcv", "market_data_ohlcv_new")
    }
    assert [p.scheduled for p in policies["market_data_ohlcv"]] == [True]
    assert [p.scheduled for p in policies["market_data_ohlcv_new"]] == [False]
    summary["rollback"] = report["exchange"]

    code, report = _cli(capsys, dsn, tmp_path, "--swap", "--accept-placeholder-coverage")
    assert code == swap.EXIT_OK, report
    assert swap.load_state(conn) == swap.SWAPPED

    # --- drop the original, VACUUM; re-runnable ---------------------------------------------------
    code, report = _cli(capsys, dsn, tmp_path, "--drop-old")
    assert code == swap.EXIT_OK, report
    assert report["state"] == swap.DONE
    summary["drop_old"] = {k: report[k] for k in ("original_bytes", "live_bytes", "vacuum_seconds")}
    code, report = _cli(capsys, dsn, tmp_path, "--drop-old")
    assert code == swap.EXIT_OK and report["state_before"] == swap.DONE
    _psql_file(dsn, _MIGRATION)  # re-applying 439 after the swap creates nothing
    assert swap.load_state(conn) == swap.DONE
    code, report = _cli(capsys, dsn, tmp_path, "--post-check")
    assert code == swap.EXIT_OK
    code, report = _cli(capsys, dsn, tmp_path, "--status")
    assert report["state"] == swap.DONE and list(report["tables"]) == ["market_data_ohlcv"]
    summary["final"] = report["tables"]

    conn.close()
    print("\nREHEARSAL SUMMARY\n" + json.dumps(summary, indent=2, default=str))
