"""Real-SQL proof of the Tradier delete script on a scratch schema (phase 191 plan 20 task 2).

The unit tests run the script on fakes, which would pass wrong SQL. Here the real modes
(--dump, --verify, --trial, --delete) run through their own functions against copies of the
seven tables in a throwaway schema on indicagent_test: the script's SQL names its tables
unqualified, so a Runtime whose connections set search_path to the scratch schema alone points
every statement there (a table missing from the scratch schema errors instead of falling back to
public). The real tables, and the live database, are never touched: the fixture asserts the
database name and the session's schema list before any write.

The seeded case covers mixed vendors, a held-back name, Tradier loads (lineage: every
ohlcv_load row stays), a Tradier load that owns an ibkr revision row (kept), a derived load that
owns a tradier revision row (the row goes, the load stays), a restatement flag on a Tradier load
(no longer a gate, since no load is deleted), a non-1d row of another vendor, a content change
after the dump (the batch digest refuses) and a crash between batches (the in-flight batch
settles). After the delete exactly the non-Tradier and held value rows remain, and restoring the
backup files reproduces every table.
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from scripts.ops.bars import ops_tradier_delete as mod
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

_TABLES = (
    "ohlcv_load",
    "ohlcv_revision",
    "ohlcv_raw",
    "market_data_ohlcv",
    "ohlcv_coverage",
    "ohlcv_request",
    "ohlcv_restatement_flag",
)
_COMPARED = _TABLES

_L = {
    name: str(uuid.UUID(int=i + 1)) for i, name in enumerate(("L1", "L2", "L3", "L4", "L5", "L6"))
}


def _day(n: int) -> str:
    return f"2020-01-{n:02d}T00:00:00+00:00"


def _seed(conn: psycopg.Connection) -> None:
    loads = [
        # (id, symbol, source, caller, detail)
        ("L1", "AAA", "tradier", "tradier-daily-loader", "line one\nline two"),
        ("L2", "AAA", "tradier", "tradier-daily-loader", None),  # owns an ibkr revision: kept
        ("L3", "BBB", "tradier", "tradier-daily-loader", None),  # carries a restatement flag
        ("L4", "BBB", "derived", "bar_derivation-daily", None),  # owns a tradier revision
        ("L5", "HLD", "tradier", "tradier-daily-loader", None),  # held back
        ("L6", "IBM", "ibkr", "ibkr-history-fetch", None),
    ]
    for key, symbol, source, caller, detail in loads:
        conn.execute(
            "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, "
            "requested_end, outcome, n_bars, caller, detail) "
            "VALUES (%s, %s, '1d', %s, '2020-01-01', '2020-01-31', 'loaded', 1, %s, %s)",
            (_L[key], symbol, source, caller, detail),
        )
    revisions = [
        ("L1", "AAA", "tradier", "consolidated", "tradier", 1),
        ("L2", "AAA", "ibkr", "named", "ibkr_named", 2),
        ("L4", "BBB", "tradier", "consolidated", "tradier", 3),
        ("L5", "HLD", "tradier", "consolidated", "tradier", 4),
    ]
    for key, symbol, vendor, kind, old_source, day in revisions:
        conn.execute(
            'INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, '
            "old_high, old_low, old_close, old_volume, old_source, vendor, kind) "
            "VALUES (%s, %s, '1d', %s, 1.5, 2.25, 1.0, 2.0, 100, %s, %s, %s)",
            (_L[key], symbol, _day(day), old_source, vendor, kind),
        )
    bars = [
        # (symbol, timeframe, vendor, kind, day)
        *[("AAA", "1d", "tradier", "consolidated", d) for d in (1, 2, 3)],
        *[("AAA", "1d", "ibkr", "smart_trades", d) for d in (2, 3)],
        *[("BBB", "1d", "tradier", "consolidated", d) for d in (1, 2)],
        ("HLD", "1d", "tradier", "consolidated", 1),
        *[("IBM", "5m", "ibkr", "smart_trades", d) for d in (1, 2)],
    ]
    for symbol, timeframe, vendor, kind, day in bars:
        conn.execute(
            'INSERT INTO ohlcv_raw ("timestamp", symbol, timeframe, vendor, kind, open, high, '
            "low, close, volume) VALUES (%s, %s, %s, %s, %s, 10.1, 11.7, 9.3, 10.9, 1000)",
            (_day(day), symbol, timeframe, vendor, kind),
        )
    canonical = [
        *[("AAA", "1d", "tradier", "consolidated", d) for d in (1, 2, 3)],
        ("AAA", "1d", "ibkr", "smart_trades", 4),
        *[("BBB", "1d", "tradier", "consolidated", d) for d in (1, 2)],
        ("HLD", "1d", "tradier", "consolidated", 1),
        ("IBM", "5m", "ibkr", "smart_trades", 1),
    ]
    for symbol, timeframe, vendor, kind, day in canonical:
        conn.execute(
            'INSERT INTO market_data_ohlcv ("timestamp", symbol, timeframe, open, high, low, '
            "close, volume, vendor, kind) VALUES (%s, %s, %s, 10.1, 11.7, 9.3, 10.9, 1000, %s, %s)",
            (_day(day), symbol, timeframe, vendor, kind),
        )
    for symbol, provider in (("BBB", "tradier"), ("AAA", "ibkr"), ("HLD", "tradier")):
        conn.execute(
            "INSERT INTO ohlcv_coverage (symbol, timeframe, provider, row_count) "
            "VALUES (%s, '1d', %s, 3)",
            (symbol, provider),
        )
    for source, route, what in (("tradier", "TRADIER", "1Day"), ("ibkr", "SMART", "TRADES")):
        conn.execute(
            "INSERT INTO ohlcv_request (request_id, fetch_run_id, symbol, timeframe, source, "
            "route, what_to_show, window_end, outcome, n_bars, caller, requested_at, answered_at) "
            "VALUES (%s, %s, 'AAA', '1d', %s, %s, %s, now(), 'bars', 3, 'test-191-20', now(), "
            "now())",
            (str(uuid.uuid4()), str(uuid.uuid4()), source, route, what),
        )
    conn.execute(
        "INSERT INTO ohlcv_restatement_flag (load_id, symbol, timeframe, vendor, kind, n_stored, "
        "n_changed, share, signatures, detail) "
        "VALUES (%s, 'BBB', '1d', 'tradier', 'consolidated', 2, 1, 0.5, '{}', 'test')",
        (_L["L3"],),
    )


@pytest.fixture
def scratch() -> Iterator[str]:
    schema = f"zz_tradier_delete_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
        conn.execute(f"CREATE SCHEMA {schema}")
        for table in _TABLES:
            conn.execute(
                f"CREATE TABLE {schema}.{table} "
                f"(LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"
            )
        conn.execute(f"ALTER TABLE {schema}.ohlcv_load ADD PRIMARY KEY (load_id)")
        conn.execute(
            f"ALTER TABLE {schema}.ohlcv_revision ADD FOREIGN KEY (load_id) "
            f"REFERENCES {schema}.ohlcv_load (load_id) ON DELETE CASCADE"
        )
        conn.execute(
            f"ALTER TABLE {schema}.ohlcv_restatement_flag ADD FOREIGN KEY (load_id) "
            f"REFERENCES {schema}.ohlcv_load (load_id) ON DELETE RESTRICT"
        )
    try:
        yield schema
    finally:
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def _scratch_connect(schema: str) -> psycopg.Connection:
    conn = psycopg.connect(
        TEST_DB_URL,
        options=f"-c search_path={schema} -c timezone=UTC -c statement_timeout=0",
    )
    database, schemas = conn.execute("SELECT current_database(), current_schemas(false)").fetchone()
    conn.rollback()
    assert database == "indicagent_test" and schemas == [schema], (database, schemas)
    return conn


def _snapshot(schema: str) -> dict[str, list[str]]:
    with _scratch_connect(schema) as conn:
        return {
            table: [row[0] for row in conn.execute(f"SELECT {table}::text FROM {table} ORDER BY 1")]
            for table in _COMPARED
        }


def _rows(schema: str, sql: str) -> list[tuple[Any, ...]]:
    with _scratch_connect(schema) as conn:
        return conn.execute(sql).fetchall()


def _execute(schema: str, sql: str, params: Any = None) -> None:
    with _scratch_connect(schema) as conn:
        conn.execute(sql, params)
        conn.commit()


def _args(tmp_path: Path, *mode: str) -> Any:
    return mod.build_parser().parse_args(
        [
            *mode,
            "--backup-dir",
            str(tmp_path / "backup"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--disk-path",
            str(tmp_path),
        ]
    )


def _restore(schema: str, backup_dir: Path, manifest: dict[str, Any]) -> None:
    files = {t["table"]: backup_dir / t["file"] for t in manifest["tables"]}
    with _scratch_connect(schema) as conn:
        with conn.cursor() as cur:
            for table in mod.RESTORE_ORDER:
                with cur.copy(f"COPY {table} FROM STDIN (FORMAT csv)") as copy:
                    copy.write(gzip.decompress(files[table].read_bytes()))
        conn.commit()


def test_dump_trial_delete_verify_and_restore_on_a_scratch_schema(scratch: str, tmp_path: Path):
    with _scratch_connect(scratch) as conn:
        _seed(conn)
        conn.commit()
    before = _snapshot(scratch)
    measures = [
        {
            "symbol": s,
            "n_tradier": 3,
            "n_residue": 1,
            "first_bar_current": "2020-01-01",
            "first_bar_after": "2020-01-02",
        }
        for s in ("AAA", "BBB", "HLD")
    ]
    rt = mod.Runtime(
        connect=lambda: _scratch_connect(scratch),
        read_apr=lambda: (0, 1, str(tmp_path)),
        measure=lambda: measures,
        tsv_path=tmp_path / "first_bar.tsv",
    )
    backup_dir = tmp_path / "backup"

    # --- dump: exact per-table, per-symbol counts; never overwrites
    assert mod.run_dump(_args(tmp_path, "--dump", "--apply", "--hold", "HLD"), rt) == 0
    manifest = json.loads((backup_dir / "tradier_delete_manifest.json").read_text())
    per_symbol = {
        t["table"]: {s: v[0] for s, v in t["per_symbol"].items()} for t in manifest["tables"]
    }
    assert per_symbol == {
        "ohlcv_revision": {"AAA": 1, "BBB": 1},
        "ohlcv_raw": {"AAA": 3, "BBB": 2},
        "market_data_ohlcv": {"AAA": 3, "BBB": 2},
        "ohlcv_coverage": {"BBB": 1},
    }
    assert manifest["held"] == ["HLD"]
    assert manifest["foreign_revisions"] == 1
    assert manifest["request_ledger"] == {"total": 2, "tradier": 1}
    assert len(list(backup_dir.glob("tradier_*.csv.gz"))) == 4
    assert mod.run_dump(_args(tmp_path, "--dump", "--apply", "--hold", "HLD"), rt) == 2

    # --- verify, then the dry-run delete changes nothing
    assert mod.run_verify(_args(tmp_path, "--verify"), rt) == 0
    assert mod.run_delete(_args(tmp_path, "--delete"), rt) == 0
    assert _snapshot(scratch) == before

    # --- trial: AAA goes (the flag on BBB's Tradier load is no gate) and the TSV comes first
    assert mod.run_trial(_args(tmp_path, "--trial", "AAA", "--apply"), rt) == 0
    assert (tmp_path / "first_bar.tsv").read_text().splitlines()[1:] == [
        "AAA\t3\t1\t2020-01-01\t2020-01-02\ttrue",
        "BBB\t3\t1\t2020-01-01\t2020-01-02\ttrue",
    ]
    trials = list((tmp_path / "logs").glob("tradier_delete_trial_AAA_*.json"))
    assert len(trials) == 1
    report = json.loads(trials[0].read_text())
    assert {t: v["rows"] for t, v in report["tables"].items()} == {
        "ohlcv_revision": 1,
        "ohlcv_raw": 3,
        "market_data_ohlcv": 3,
        "ohlcv_coverage": 0,
    }

    # --- a content change after the dump: same counts, different digest, batch refused
    _execute(
        scratch,
        "UPDATE ohlcv_raw SET close = 10.8 WHERE symbol = 'BBB' AND vendor = 'tradier' "
        'AND "timestamp" = %s',
        (_day(1),),
    )
    assert mod.run_delete(_args(tmp_path, "--delete", "--apply"), rt) == 2
    assert _rows(scratch, "SELECT count(*) FROM ohlcv_raw WHERE symbol = 'BBB'") == [(2,)]
    _execute(
        scratch,
        "UPDATE ohlcv_raw SET close = 10.9 WHERE symbol = 'BBB' AND vendor = 'tradier' "
        'AND "timestamp" = %s',
        (_day(1),),
    )

    # --- a crash left BBB in flight with nothing committed: the rerun settles it and finishes
    state_path = tmp_path / "logs" / "tradier_delete_state.json"
    state = json.loads(state_path.read_text())
    state["in_flight"] = {
        "symbols": ["BBB"],
        "trial": False,
        "free_bytes_before": 1,
        "started": "2026-10-27T00:00:00+00:00",
    }
    state_path.write_text(json.dumps(state))
    assert mod.run_delete(_args(tmp_path, "--delete", "--apply"), rt) == 0
    assert mod.run_verify(_args(tmp_path, "--verify", "--require-complete"), rt) == 0

    # --- exactly the non-Tradier and held value rows remain; every load and the flag stay
    assert _rows(scratch, "SELECT load_id::text FROM ohlcv_load ORDER BY 1") == [
        (_L[k],) for k in ("L1", "L2", "L3", "L4", "L5", "L6")
    ]
    assert _rows(scratch, "SELECT count(*) FROM ohlcv_restatement_flag") == [(1,)]
    assert _rows(scratch, "SELECT symbol, vendor FROM ohlcv_revision ORDER BY 1, 2") == [
        ("AAA", "ibkr"),
        ("HLD", "tradier"),
    ]
    assert _rows(
        scratch,
        "SELECT symbol, timeframe, vendor, count(*) FROM ohlcv_raw GROUP BY 1, 2, 3 "
        "ORDER BY 1, 2, 3",
    ) == [("AAA", "1d", "ibkr", 2), ("HLD", "1d", "tradier", 1), ("IBM", "5m", "ibkr", 2)]
    assert _rows(
        scratch,
        "SELECT symbol, timeframe, vendor, count(*) FROM market_data_ohlcv GROUP BY 1, 2, 3 "
        "ORDER BY 1, 2, 3",
    ) == [("AAA", "1d", "ibkr", 1), ("HLD", "1d", "tradier", 1), ("IBM", "5m", "ibkr", 1)]
    assert _rows(scratch, "SELECT symbol, provider FROM ohlcv_coverage ORDER BY 1") == [
        ("AAA", "ibkr"),
        ("HLD", "tradier"),
    ]
    assert _rows(scratch, "SELECT count(*) FROM ohlcv_request") == [(2,)]

    # --- the backup round-trips: restoring the files reproduces every table
    _restore(scratch, backup_dir, manifest)
    assert _snapshot(scratch) == before
