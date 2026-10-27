"""Tradier source-scoped deletion: backup, trial, batched delete, verify (phase 191 plan 20).

Design doc `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, "Owner exception: Tradier
deletion" and migration step 10; todo 533 Tradier retirement step 4. The owner ruled 2026-10-12
that Tradier is not used at all and its data is junk; after IBKR was asked for every span
Tradier covers and the residue was measured (plan 19), every Tradier-sourced row is deleted
from the bar tables, behind a COPY backup kept until about 2026-11-12. The fetch ledger
ohlcv_request is permanent and keeps its Tradier-route rows.

One exact predicate per table, each excluding the held-back names the owner names at the
checkpoint (`--hold`, recorded in the manifest at `--dump` and read from it afterwards):

- ohlcv_revision: vendor = 'tradier' (old Tradier values, under any load, deleted explicitly);
- ohlcv_load: source = 'tradier', except a Tradier load that owns an ohlcv_revision row of
  another vendor. The Tradier loader displaced IBKR canonical values on 2026-10-03 and the old
  IBKR values sit in ohlcv_revision under its loads (vendor ibkr); ON DELETE CASCADE would take
  that IBKR evidence with the load, so such loads are kept and counted as retained;
- ohlcv_raw: vendor = 'tradier' and timeframe = '1d';
- market_data_ohlcv: vendor = 'tradier' and timeframe = '1d';
- ohlcv_coverage: provider = 'tradier'.

Modes (every write needs `--apply`; without it a mode reports and writes nothing):

- `--dump`: per table, `COPY (SELECT * FROM <table> WHERE <predicate>) TO STDOUT` into
  data/backups/191/tradier_<table>_<UTC date>.csv.gz inside one REPEATABLE READ transaction,
  plus a manifest of per-table and per-symbol row counts and content digests (md5 over the
  ordered row text), file sha256, the retained-load count, the count of other-vendor revision
  rows under Tradier loads and the ohlcv_request counts. The file's CSV records are recounted
  and must equal count(*). The dump never overwrites: it refuses while any tradier_* backup file
  exists, opens each file exclusively and fsyncs every file before the manifest is written.
- `--verify`: recounts the live Tradier rows per (table, symbol) and reads every backup file
  back (CSV records and sha256), comparing both with the manifest; symbols the delete state
  records as done must hold zero rows. Also checks the retained-load count, the other-vendor
  revision count, that the ohlcv_request Tradier count is unchanged and that its total has not
  shrunk. `--require-complete` additionally fails unless every symbol is deleted.
- `--trial SYMBOL`: writes the first-bar change TSV if not yet written, then deletes exactly one
  symbol's Tradier rows, timing each table and reading the free-disk delta, and writes
  logs/tradier_delete_trial_<SYMBOL>_<UTC>.json.
- `--delete`: refuses without a manifest that verifies, without a trial whose disk delta
  extrapolated over the remaining rows fits in the free space minus the APR floor, or while an
  ohlcv_restatement_flag row references a load to delete (ON DELETE RESTRICT). It writes the
  first-bar change TSV before the first delete (unless the trial did), then deletes per symbol
  batch (APR `infra.tradier_delete.batch_symbols`), one REPEATABLE READ transaction per batch
  across the five tables; before every batch it reads free disk and stops (exit 3, state saved)
  below APR `infra.tradier_delete.min_free_disk_gb`.

Inside every batch transaction, before any delete, each (table, symbol) is recounted and its
content digest recomputed; any difference from the manifest refuses the batch. Every DELETE's
row count must then equal the manifest's total for the batch, and a load delete that would
cascade into any ohlcv_revision row is refused; each refusal rolls the batch back. Progress lives
in logs/tradier_delete_state.json, bound to the manifest's sha256. A batch's symbols are recorded
as in flight before its transaction starts; a rerun after a crash settles them by the live
counts (zero in every table: committed, done; the manifest's counts: rolled back, pending;
anything else refuses), and a trial settled as committed gets its report written then.

Why plain DELETE batches (plan amendment 2026-10-13): compressed_hypertable_write_session
(decompress=False included) is hardened for feature_vectors and feature_ic_scores only and
commits the caller's transaction, so it cannot hold a per-batch transaction here. The deletes
use TimescaleDB's native DML decompression (the per-transaction tuple limit is lifted inside
each batch). vendor is a segmentby column on ohlcv_raw, so its Tradier batches go whole; on
market_data_ohlcv the segmentby is (symbol, timeframe), so a Tradier delete decompresses the
name's 1d segments in every chunk it touches, and the decompressed survivors stay
uncompressed until the compression policy runs: that is what the trial measures. After the
run the operator issues bare `VACUUM ohlcv_raw;`, `VACUUM market_data_ohlcv;`,
`VACUUM ohlcv_load;` and `VACUUM ohlcv_revision;`.

The free disk is read on the root filesystem by default, which holds the database volume
(/var/lib/docker/volumes/production_timescale-data) and data/backups/. Sessions run with
statement_timeout 0: the dump's scans and digests outlast the role's default timeout.

Table names in the SQL are unqualified, so they resolve through the session search_path; the
integration test points a Runtime at a scratch schema on indicagent_test that way.

TEMPORARY: retire with the backup at plan 191-25 (the two APR keys go with it).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import get_settings  # noqa: E402

MIN_FREE_DISK_KEY = "infra.tradier_delete.min_free_disk_gb"
BATCH_SYMBOLS_KEY = "infra.tradier_delete.batch_symbols"
RETENTION_UNTIL = "2026-11-12"

EXIT_OK = 0
EXIT_VERIFY_FAILED = 1
EXIT_REFUSED = 2
EXIT_DISK_ABORT = 3

_BACKUP_DIR = project_root / "data" / "backups" / "191"
_MANIFEST_NAME = "tradier_delete_manifest.json"
_BACKUP_GLOB = "tradier_*.csv.gz"
_LOG_DIR = project_root / "logs"
_STATE_NAME = "tradier_delete_state.json"
_TRIAL_PREFIX = "tradier_delete_trial_"
_TSV_PATH = (
    project_root
    / ".planning"
    / "phases"
    / "191-unified-raw-bar-table"
    / "191-TRADIER-FIRST-BAR-CHANGES.tsv"
)
_GIB = 2**30
_READ_BLOCK = 1 << 20

# --- the one predicate per table ----------------------------------------------------------------

_HELD = "NOT (symbol = ANY(%(held)s::text[]))"
_BATCH = "symbol = ANY(%(batch)s::text[])"

LOAD_KEEPS_FOREIGN_REVISIONS = (
    " AND NOT EXISTS (SELECT 1 FROM ohlcv_revision v"
    " WHERE v.load_id = ohlcv_load.load_id AND v.vendor <> 'tradier')"
)

_REVISION_PREDICATE = "vendor = 'tradier' AND " + _HELD
_LOAD_PREDICATE = "source = 'tradier' AND " + _HELD + LOAD_KEEPS_FOREIGN_REVISIONS
# timeframe is a segmentby column on both bar hypertables and vendor is not one on
# market_data_ohlcv: without it, a symbol-batch delete there decompresses every timeframe of the
# name (AAPL: 611k rows for 6.7k Tradier 1d rows). Every Tradier bar is 1d; the dump refuses
# while any Tradier bar of another timeframe exists (_OFF_TIMEFRAME_SQL), so the predicate stays
# exact.
_RAW_PREDICATE = "vendor = 'tradier' AND timeframe = '1d' AND " + _HELD
_CANONICAL_PREDICATE = "vendor = 'tradier' AND timeframe = '1d' AND " + _HELD
_COVERAGE_PREDICATE = "provider = 'tradier' AND " + _HELD

# Written out literally so the single-writer boundary tests see each statement.
_DELETE_REVISION_SQL = "DELETE FROM ohlcv_revision WHERE " + _BATCH + " AND " + _REVISION_PREDICATE
_DELETE_LOAD_SQL = "DELETE FROM ohlcv_load WHERE " + _BATCH + " AND " + _LOAD_PREDICATE
_DELETE_RAW_SQL = "DELETE FROM ohlcv_raw WHERE " + _BATCH + " AND " + _RAW_PREDICATE
_DELETE_CANONICAL_SQL = (
    "DELETE FROM market_data_ohlcv WHERE " + _BATCH + " AND " + _CANONICAL_PREDICATE
)
_DELETE_COVERAGE_SQL = "DELETE FROM ohlcv_coverage WHERE " + _BATCH + " AND " + _COVERAGE_PREDICATE


@dataclass(frozen=True)
class TableSpec:
    table: str
    predicate: str
    delete_sql: str

    @property
    def count_sql(self) -> str:
        return f"SELECT symbol, count(*) FROM {self.table} WHERE {self.predicate} GROUP BY symbol"

    @property
    def batch_count_sql(self) -> str:
        return (
            f"SELECT symbol, count(*) FROM {self.table} WHERE {_BATCH} AND {self.predicate} "
            "GROUP BY symbol"
        )

    @property
    def select_sql(self) -> str:
        return f"SELECT * FROM {self.table} WHERE {self.predicate}"

    def _digest_sql(self, where: str) -> str:
        # The whole-row text of every selected row, ordered by that text, so the digest depends
        # on content only. Sessions run with timezone UTC, so timestamps render the same way.
        row = f"{self.table}::text"
        return (
            f"SELECT symbol, count(*), md5(string_agg({row}, E'\\n' ORDER BY {row})) "
            f"FROM {self.table} WHERE {where} GROUP BY symbol"
        )

    @property
    def digest_sql(self) -> str:
        return self._digest_sql(self.predicate)

    @property
    def batch_digest_sql(self) -> str:
        return self._digest_sql(f"{_BATCH} AND {self.predicate}")


# Delete order inside a batch: Tradier revision rows first, so the load delete cascades into
# nothing (checked), then the loads, then the bar tables and the coverage ledger.
TABLES: tuple[TableSpec, ...] = (
    TableSpec("ohlcv_revision", _REVISION_PREDICATE, _DELETE_REVISION_SQL),
    TableSpec("ohlcv_load", _LOAD_PREDICATE, _DELETE_LOAD_SQL),
    TableSpec("ohlcv_raw", _RAW_PREDICATE, _DELETE_RAW_SQL),
    TableSpec("market_data_ohlcv", _CANONICAL_PREDICATE, _DELETE_CANONICAL_SQL),
    TableSpec("ohlcv_coverage", _COVERAGE_PREDICATE, _DELETE_COVERAGE_SQL),
)
SPECS: dict[str, TableSpec] = {spec.table: spec for spec in TABLES}
# Restore order from the backup files: loads before the revision rows that reference them.
RESTORE_ORDER: tuple[str, ...] = (
    "ohlcv_load",
    "ohlcv_revision",
    "ohlcv_raw",
    "market_data_ohlcv",
    "ohlcv_coverage",
)

DECOMPRESSION_LIMIT_SQL = "SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0"

# Revision rows a batch's load delete would cascade into; must be zero once the batch's Tradier
# revision rows are gone, since loads owning another vendor's revisions are kept.
CASCADE_CHECK_SQL = (
    "SELECT count(*) FROM ohlcv_revision r WHERE r.load_id IN "
    "(SELECT load_id FROM ohlcv_load WHERE " + _BATCH + " AND " + _LOAD_PREDICATE + ")"
)
RESTATEMENT_FLAG_SQL = (
    "SELECT count(*) FROM ohlcv_restatement_flag f WHERE f.load_id IN "
    "(SELECT load_id FROM ohlcv_load WHERE " + _LOAD_PREDICATE + ")"
)
_RETAINED_LOADS_SQL = (
    "SELECT count(*) FROM ohlcv_load WHERE source = 'tradier' AND "
    + _HELD
    + " AND EXISTS (SELECT 1 FROM ohlcv_revision v"
    " WHERE v.load_id = ohlcv_load.load_id AND v.vendor <> 'tradier')"
)
# Other-vendor revision rows under Tradier loads (3,179,829 ibkr rows on 2026-10-27): the
# evidence the retained loads protect; it must not move (T-191-45).
_FOREIGN_REVISIONS_SQL = (
    "SELECT count(*) FROM ohlcv_revision v JOIN ohlcv_load l ON l.load_id = v.load_id "
    "WHERE l.source = 'tradier' AND v.vendor <> 'tradier'"
)
_OFF_TIMEFRAME_SQL = (
    "SELECT (SELECT count(*) FROM ohlcv_raw WHERE vendor = 'tradier' AND timeframe <> '1d'), "
    "(SELECT count(*) FROM market_data_ohlcv WHERE vendor = 'tradier' AND timeframe <> '1d')"
)
_LEDGER_SQL = "SELECT count(*), count(*) FILTER (WHERE source = 'tradier') FROM ohlcv_request"


class DeleteRefused(RuntimeError):
    """A batch that would delete anything other than the manifest's rows; rolled back."""


# --- held-back names -------------------------------------------------------------------------


def parse_held(value: str | None) -> list[str]:
    """`--hold AAA,BBB` as a sorted upper-case list; an empty item is a typo, refused."""
    if value is None:
        return []
    items = [item.strip().upper() for item in value.split(",")]
    if any(not item for item in items):
        raise SystemExit(f"--hold has an empty item: {value!r}")
    return sorted(set(items))


# --- files -----------------------------------------------------------------------------------


def backup_file_name(table: str, day: date) -> str:
    return f"tradier_{table}_{day.isoformat()}.csv.gz"


def existing_backups(backup_dir: Path) -> list[str]:
    return sorted(p.name for p in backup_dir.glob(_BACKUP_GLOB)) if backup_dir.exists() else []


def count_csv_records(path: Path) -> int:
    """CSV records in a gzip file, parsed (a quoted field may hold a newline: ohlcv_load.detail)."""
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        return sum(1 for _ in csv.reader(stream))


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_READ_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# --- the manifest check ----------------------------------------------------------------------


def manifest_symbols(manifest: Mapping[str, Any]) -> list[str]:
    return sorted({s for t in manifest["tables"] for s in t["per_symbol"]})


def expected_counts(manifest: Mapping[str, Any], batch: Sequence[str]) -> dict[str, int]:
    return {
        t["table"]: sum(int(t["per_symbol"].get(s, 0)) for s in batch) for t in manifest["tables"]
    }


def expected_content(
    manifest: Mapping[str, Any], batch: Sequence[str]
) -> dict[str, dict[str, tuple[int, str]]]:
    """table -> symbol -> (row count, md5) for the batch's symbols holding rows there."""
    return {
        t["table"]: {
            s: (int(t["per_symbol"][s]), t["per_symbol_md5"][s])
            for s in batch
            if int(t["per_symbol"].get(s, 0))
        }
        for t in manifest["tables"]
    }


def verify_problems(
    manifest: Mapping[str, Any],
    *,
    live: Mapping[str, Mapping[str, int]],
    files: Mapping[str, int],
    digests: Mapping[str, str],
    completed: set[str],
    retained_live: int,
    foreign_revisions_live: int,
    ledger_live: Mapping[str, int],
) -> list[str]:
    """Every disagreement between the manifest and the database or the files, one message each.

    A symbol the delete state records as done must hold zero live rows; every other symbol must
    hold exactly its manifest count, and a live symbol the manifest lacks is a problem.
    """
    problems: list[str] = []
    for entry in manifest["tables"]:
        table = entry["table"]
        recorded = {s: int(n) for s, n in entry["per_symbol"].items()}
        observed = live.get(table, {})
        for symbol in sorted(set(recorded) | set(observed)):
            want = 0 if symbol in completed else recorded.get(symbol, 0)
            have = int(observed.get(symbol, 0))
            if have != want:
                problems.append(f"{table} {symbol}: live {have} != expected {want}")
        rows = int(entry["rows"])
        if table not in files:
            problems.append(f"{table}: file {entry['file']} missing")
        elif files[table] != rows:
            problems.append(f"{table}: file rows {files[table]} != manifest {rows}")
        if table in digests and digests[table] != entry["sha256"]:
            problems.append(f"{table}: sha256 of {entry['file']} changed")
    if retained_live != int(manifest["retained_loads"]):
        problems.append(
            f"ohlcv_load: retained Tradier loads {retained_live} != manifest "
            f"{manifest['retained_loads']}"
        )
    if foreign_revisions_live != int(manifest["foreign_revisions"]):
        problems.append(
            f"ohlcv_revision: other-vendor rows under Tradier loads {foreign_revisions_live} "
            f"!= manifest {manifest['foreign_revisions']}"
        )
    ledger = manifest["request_ledger"]
    if int(ledger_live["tradier"]) != int(ledger["tradier"]):
        problems.append(
            f"ohlcv_request: tradier rows {ledger_live['tradier']} != manifest {ledger['tradier']}"
        )
    if int(ledger_live["total"]) < int(ledger["total"]):
        problems.append(
            f"ohlcv_request: total rows {ledger_live['total']} < manifest {ledger['total']}"
        )
    return problems


# --- state -----------------------------------------------------------------------------------


def new_state(manifest_sha256: str) -> dict[str, Any]:
    return {
        "manifest_sha256": manifest_sha256,
        "completed": [],
        "in_flight": None,
        "batches": [],
        "tsv_written": False,
        "aborted": None,
        "complete": False,
    }


def save_state(state: Mapping[str, Any], path: Path) -> None:
    """Atomic replace, so a crash never leaves a half-written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as stream:
        stream.write(json.dumps(state, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


@dataclass
class Settlement:
    """How the in-flight symbols of a crashed run stand against the live counts."""

    committed: list[str] = field(default_factory=list)
    rolled_back: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)


def settle(
    manifest: Mapping[str, Any], symbols: Sequence[str], live: Mapping[str, Mapping[str, int]]
) -> Settlement:
    """Committed: zero live rows in every table; rolled back: exactly the manifest's counts in
    every table; anything else is partial. One transaction per batch makes partial impossible
    unless something else wrote, so a partial symbol refuses the run."""
    out = Settlement()
    for symbol in symbols:
        pairs = [
            (int(t["per_symbol"].get(symbol, 0)), int(live.get(t["table"], {}).get(symbol, 0)))
            for t in manifest["tables"]
        ]
        if all(have == 0 for _, have in pairs):
            out.committed.append(symbol)
        elif all(have == want for want, have in pairs):
            out.rolled_back.append(symbol)
        else:
            out.partial.append(symbol)
    return out


def apply_settlement(state: dict[str, Any], settlement: Settlement) -> str | None:
    """Folds a settlement into the state; returns a refusal when any symbol is partial."""
    if settlement.partial:
        return (
            f"in-flight symbols {settlement.partial} are partly deleted; the live rows match "
            "neither the manifest nor zero"
        )
    state["completed"] = sorted(set(state["completed"]) | set(settlement.committed))
    state["in_flight"] = None
    return None


# --- the trial gate --------------------------------------------------------------------------


def trial_refusal(
    report: Mapping[str, Any] | None, remaining_rows: int, free_bytes: int, floor_bytes: int
) -> str | None:
    """A refusal unless the trial's disk growth per row, over the remaining rows, fits in the
    free space above the floor. A trial that freed disk counts as zero growth."""
    if report is None:
        return "no trial report for this manifest: run --trial SYMBOL --apply first"
    if report.get("recovered"):
        return (
            "the latest trial report was recovered after a crash (no per-table timings, and its "
            "disk delta spans the crash); run a fresh trial on another symbol"
        )
    rows = int(report["rows_total"])
    if rows <= 0:
        return "the trial deleted no rows; its disk delta says nothing"
    per_row = max(0, int(report["disk_delta_bytes"])) / rows
    projected = int(per_row * remaining_rows)
    budget = free_bytes - floor_bytes
    if projected >= budget:
        return (
            f"projected disk growth {projected} bytes ({per_row:.1f} bytes/row over "
            f"{remaining_rows} rows) is not below free {free_bytes} minus floor {floor_bytes} "
            f"({budget} bytes)"
        )
    return None


# --- one batch -------------------------------------------------------------------------------


def delete_batch(
    conn: Any,
    batch: Sequence[str],
    held: Sequence[str],
    expected: Mapping[str, Mapping[str, tuple[int, str]]],
    *,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> dict[str, dict[str, Any]]:
    """Delete one symbol batch from the five tables in one REPEATABLE READ transaction.

    Before any delete, each (table, symbol) is recounted and its content digest recomputed in the
    transaction's snapshot and must equal the manifest; then every DELETE's row count must equal
    the batch's manifest total and the load delete must cascade into nothing. Any difference
    raises DeleteRefused and rolls the whole batch back. The connection returns to READ COMMITTED
    however the batch ends.
    """
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    try:
        return _delete_batch_transaction(
            conn, batch, held, expected, free_bytes=free_bytes, clock=clock
        )
    finally:
        conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED


def _delete_batch_transaction(
    conn: Any,
    batch: Sequence[str],
    held: Sequence[str],
    expected: Mapping[str, Mapping[str, tuple[int, str]]],
    *,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> dict[str, dict[str, Any]]:
    """delete_batch's transaction (the caller sets and resets the isolation level)."""
    params = {"batch": list(batch), "held": list(held)}
    timings: dict[str, dict[str, Any]] = {}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(DECOMPRESSION_LIMIT_SQL)
            for spec in TABLES:
                cur.execute(spec.batch_digest_sql, params)
                found = {s: (int(n), md5) for s, n, md5 in cur.fetchall()}
                want = dict(expected[spec.table])
                if found != want:
                    differing = sorted(
                        s for s in set(found) | set(want) if found.get(s) != want.get(s)
                    )
                    raise DeleteRefused(
                        f"batch {list(batch)}: {spec.table} content differs from the manifest "
                        f"for {differing}"
                    )
            for spec in TABLES:
                if spec.table == "ohlcv_load":
                    cur.execute(CASCADE_CHECK_SQL, params)
                    cascading = int(cur.fetchone()[0])
                    if cascading:
                        raise DeleteRefused(
                            f"batch {list(batch)}: the load delete would cascade into "
                            f"{cascading} ohlcv_revision rows"
                        )
                want_rows = sum(n for n, _ in expected[spec.table].values())
                free_before = free_bytes()
                started = clock()
                cur.execute(spec.delete_sql, params)
                deleted = cur.rowcount
                elapsed = clock() - started
                free_after = free_bytes()
                if deleted != want_rows:
                    raise DeleteRefused(
                        f"batch {list(batch)}: {spec.table} deleted {deleted} rows, "
                        f"manifest {want_rows}"
                    )
                timings[spec.table] = {
                    "rows": deleted,
                    "seconds": round(elapsed, 3),
                    "disk_delta_bytes": free_before - free_after,
                }
    return timings


def _begin_flight(
    state: dict[str, Any], state_path: Path, batch: Sequence[str], free: int, *, trial: bool
) -> None:
    state["in_flight"] = {
        "symbols": list(batch),
        "trial": trial,
        "free_bytes_before": free,
        "started": datetime.now(UTC).isoformat(),
    }
    save_state(state, state_path)


# --- the batch run ---------------------------------------------------------------------------


def run_batches(
    conn: Any,
    manifest: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    *,
    batch_symbols: int,
    floor_bytes: int,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> int:
    """Delete the not-yet-done symbols in batches; the disk guard runs before every batch."""
    if batch_symbols < 1:
        raise ValueError(f"batch size must be >= 1, got {batch_symbols}")
    if state.get("in_flight"):
        raise ValueError("unsettled in-flight batch; settle it before running batches")
    done = set(state["completed"])
    pending = [s for s in manifest_symbols(manifest) if s not in done]
    held = list(manifest["held"])
    state["aborted"] = None
    for start in range(0, len(pending), batch_symbols):
        batch = pending[start : start + batch_symbols]
        free = free_bytes()
        if free < floor_bytes:
            state["aborted"] = {
                "reason": "free disk below floor",
                "free_bytes": free,
                "floor_bytes": floor_bytes,
                "next_batch": batch,
                "at": datetime.now(UTC).isoformat(),
            }
            save_state(state, state_path)
            print(
                f"ABORT: free disk {free} bytes below floor {floor_bytes}; "
                f"{len(done)} symbols done, {len(pending) - start} left; state {state_path}",
                file=sys.stderr,
            )
            return EXIT_DISK_ABORT
        _begin_flight(state, state_path, batch, free, trial=False)
        try:
            timings = delete_batch(
                conn,
                batch,
                held,
                expected_content(manifest, batch),
                free_bytes=free_bytes,
                clock=clock,
            )
        except DeleteRefused as error:
            state["in_flight"] = None
            state["aborted"] = {
                "reason": str(error),
                "next_batch": batch,
                "at": datetime.now(UTC).isoformat(),
            }
            save_state(state, state_path)
            print(f"REFUSED (batch rolled back): {error}", file=sys.stderr)
            return EXIT_REFUSED
        state["completed"] = sorted(done | set(batch))
        state["in_flight"] = None
        done = set(state["completed"])
        state["batches"].append({"symbols": batch, "free_bytes_before": free, "tables": timings})
        save_state(state, state_path)
        print(
            f"batch {start // batch_symbols + 1}: {len(batch)} symbols, "
            f"{sum(t['rows'] for t in timings.values())} rows; {len(done)} done",
            flush=True,
        )
    state["complete"] = set(manifest_symbols(manifest)) <= done
    save_state(state, state_path)
    return EXIT_OK


def apply_delete(
    *,
    conn: Any,
    manifest: Mapping[str, Any] | None,
    manifest_sha256: str,
    state: dict[str, Any],
    state_path: Path,
    verify: Callable[[], list[str]],
    trial_report: Mapping[str, Any] | None,
    restatement_flags: int,
    write_tsv: Callable[[], None],
    batch_symbols: int,
    floor_bytes: int,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> int:
    """The gated batch delete: manifest, verify, trial, flags, TSV, then the batches.

    The caller settles any in-flight batch before calling (state["in_flight"] must be empty).
    """
    if manifest is None:
        print("REFUSED: no manifest; run --dump --apply and --verify first", file=sys.stderr)
        return EXIT_REFUSED
    if state["manifest_sha256"] != manifest_sha256:
        print("REFUSED: the delete state belongs to another manifest", file=sys.stderr)
        return EXIT_REFUSED
    if state.get("in_flight"):
        print("REFUSED: an in-flight batch is unsettled", file=sys.stderr)
        return EXIT_REFUSED
    problems = verify()
    if problems:
        print(f"REFUSED: manifest does not verify ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_REFUSED
    done = set(state["completed"])
    remaining = sum(
        int(n)
        for t in manifest["tables"]
        for symbol, n in t["per_symbol"].items()
        if symbol not in done
    )
    refusal = trial_refusal(trial_report, remaining, free_bytes(), floor_bytes)
    if refusal is not None:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    if restatement_flags:
        print(
            f"REFUSED: {restatement_flags} ohlcv_restatement_flag rows reference loads to delete",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    ensure_tsv(state, state_path, write_tsv)
    return run_batches(
        conn,
        manifest,
        state,
        state_path,
        batch_symbols=batch_symbols,
        floor_bytes=floor_bytes,
        free_bytes=free_bytes,
        clock=clock,
    )


# --- first-bar change record -----------------------------------------------------------------

_TSV_COLUMNS = (
    "symbol",
    "n_tradier_sessions",
    "n_residue_sessions",
    "first_bar_current",
    "first_bar_after",
    "first_bar_changed",
)


def ensure_tsv(state: dict[str, Any], state_path: Path, write_tsv: Callable[[], None]) -> None:
    """Writes the first-bar TSV once, before the first delete of any kind (trial or batch)."""
    if not state["tsv_written"]:
        write_tsv()
        state["tsv_written"] = True
        save_state(state, state_path)


def render_first_bar_tsv(measures: Sequence[Mapping[str, Any]], held: Sequence[str]) -> str:
    """One row per Tradier name (held-back names excluded), from plan 19's --measure: the
    stored first canonical 1d bar now and the first IBKR smart_trades bar after (none: the
    name loses its whole 1d history)."""
    lines = ["\t".join(_TSV_COLUMNS)]
    held_set = set(held)
    for m in sorted(measures, key=lambda m: m["symbol"]):
        if m["symbol"] in held_set:
            continue
        current = m["first_bar_current"]
        after = m["first_bar_after"]
        lines.append(
            "\t".join(
                (
                    m["symbol"],
                    str(m["n_tradier"]),
                    str(m["n_residue"]),
                    str(current) if current is not None else "none",
                    str(after) if after is not None else "none",
                    "true" if after != current else "false",
                )
            )
        )
    return "\n".join(lines) + "\n"


def _measure_first_bars() -> list[dict[str, Any]]:
    """Plan 19's --measure over every Tradier name (read-only connection), as JSON rows."""
    from scripts.ops.bars import ops_tradier_residue as residue

    async def _run() -> dict[str, Any]:
        conn = await residue.open_readonly_connection()
        try:
            return await residue.run_measure(conn)
        finally:
            await conn.close()

    measured = asyncio.run(_run())
    return [
        {
            "symbol": m["symbol"],
            "n_tradier": m["n_tradier"],
            "n_residue": m["n_residue"],
            "first_bar_current": m["first_bar_current"],
            "first_bar_after": m["first_bar_after"],
        }
        for m in measured["names"]
    ]


# --- dry-run counts --------------------------------------------------------------------------


def plan_counts(conn: Any, held: Sequence[str]) -> dict[str, dict[str, int]]:
    """Per-table, per-symbol Tradier row counts under the predicates; SELECTs only."""
    counts: dict[str, dict[str, int]] = {}
    with conn.cursor() as cur:
        for spec in TABLES:
            cur.execute(spec.count_sql, {"held": list(held)})
            counts[spec.table] = {symbol: int(n) for symbol, n in cur.fetchall()}
    return counts


def batch_counts(conn: Any, batch: Sequence[str], held: Sequence[str]) -> dict[str, dict[str, int]]:
    """plan_counts restricted to a batch of symbols (the in-flight settlement read)."""
    counts: dict[str, dict[str, int]] = {}
    with conn.cursor() as cur:
        for spec in TABLES:
            cur.execute(spec.batch_count_sql, {"batch": list(batch), "held": list(held)})
            counts[spec.table] = {symbol: int(n) for symbol, n in cur.fetchall()}
    return counts


# --- runtime (production defaults; the integration test injects a scratch target) -------------


def _connect() -> psycopg.Connection:
    """The production connection; its unqualified table names must resolve to public only."""
    conn = psycopg.connect(
        get_settings().database_url, options="-c timezone=UTC -c statement_timeout=0"
    )
    schemas = conn.execute("SELECT current_schemas(false)").fetchone()[0]
    conn.rollback()
    if list(schemas) != ["public"]:
        conn.close()
        raise SystemExit(f"REFUSED: session schemas {schemas}, expected ['public'] only")
    return conn


async def _read_apr_async() -> tuple[int, int]:
    cfg = ConfigService(get_settings().database_url)
    await cfg.initialize()
    try:
        floor_gb = int(await cfg.get(MIN_FREE_DISK_KEY, 200))
        batch = int(await cfg.get(BATCH_SYMBOLS_KEY, 20))
    finally:
        await cfg.close()
    return floor_gb, batch


def _read_apr() -> tuple[int, int]:
    return asyncio.run(_read_apr_async())


@dataclass(frozen=True)
class Runtime:
    """Where the script reads and writes: the database connection, the APR values
    (floor GiB, batch symbols), the first-bar measurement and the TSV path."""

    connect: Callable[[], psycopg.Connection]
    read_apr: Callable[[], tuple[int, int]]
    measure: Callable[[], list[dict[str, Any]]]
    tsv_path: Path


PRODUCTION = Runtime(
    connect=_connect, read_apr=_read_apr, measure=_measure_first_bars, tsv_path=_TSV_PATH
)


# --- database plumbing -----------------------------------------------------------------------


def _scalar(conn: psycopg.Connection, sql: str, params: Any = None) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _ledger(conn: psycopg.Connection) -> dict[str, int]:
    total, tradier = _scalar(conn, _LEDGER_SQL)
    return {"total": int(total), "tradier": int(tradier)}


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [row[0] for row in cur.fetchall()]


def _digests(conn: psycopg.Connection, held: Sequence[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        for spec in TABLES:
            cur.execute(spec.digest_sql, {"held": list(held)})
            out[spec.table] = {s: (int(n), md5) for s, n, md5 in cur.fetchall()}
    return out


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    return args.backup_dir / _MANIFEST_NAME, args.log_dir / _STATE_NAME


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, ""
    text = path.read_text()
    return json.loads(text), _sha256_of_text(text)


def _load_state(path: Path, manifest_sha256: str) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text())
        state.setdefault("in_flight", None)
        return state
    return new_state(manifest_sha256)


def _latest_trial(log_dir: Path, manifest_sha256: str) -> dict[str, Any] | None:
    reports = [json.loads(p.read_text()) for p in sorted(log_dir.glob(f"{_TRIAL_PREFIX}*.json"))]
    matching = [r for r in reports if r.get("manifest_sha256") == manifest_sha256]
    return max(matching, key=lambda r: r["finished"]) if matching else None


def _held_for(args: argparse.Namespace, manifest: Mapping[str, Any] | None) -> list[str]:
    """The manifest's held list; a different --hold after the dump is refused."""
    given = parse_held(args.hold)
    if manifest is None:
        return given
    if args.hold is not None and given != list(manifest["held"]):
        raise SystemExit(
            f"--hold {given} differs from the manifest's held list {manifest['held']}; "
            "the held list is fixed at --dump"
        )
    return list(manifest["held"])


def _free_reader(path: Path) -> Callable[[], int]:
    return lambda: shutil.disk_usage(path).free


def _write_trial_report(log_dir: Path, report: Mapping[str, Any]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"{_TRIAL_PREFIX}{report['symbol']}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"trial report: {path}")
    return path


def _settle_in_flight(
    conn: psycopg.Connection,
    manifest: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    log_dir: Path,
    free_bytes: Callable[[], int],
    digest: str,
) -> str | None:
    """Settles a crashed run's in-flight batch from the live counts and saves the state; a
    committed trial gets its (recovered) report. Returns a refusal for a partial symbol."""
    flight = state.get("in_flight")
    if not flight:
        return None
    symbols = list(flight["symbols"])
    live = batch_counts(conn, symbols, list(manifest["held"]))
    conn.rollback()
    settlement = settle(manifest, symbols, live)
    refusal = apply_settlement(state, settlement)
    if refusal is not None:
        return refusal
    save_state(state, state_path)
    print(
        f"settled in-flight batch: committed {settlement.committed}, "
        f"rolled back {settlement.rolled_back}"
    )
    if flight.get("trial") and settlement.committed:
        symbol = settlement.committed[0]
        free_now = free_bytes()
        rows = sum(expected_counts(manifest, [symbol]).values())
        _write_trial_report(
            log_dir,
            {
                "symbol": symbol,
                "manifest_sha256": digest,
                "recovered": True,
                "started": flight["started"],
                "finished": datetime.now(UTC).isoformat(),
                "tables": None,
                "rows_total": rows,
                "seconds_total": None,
                "free_bytes_before": flight["free_bytes_before"],
                "free_bytes_after_commit": free_now,
                "disk_delta_bytes": int(flight["free_bytes_before"]) - free_now,
            },
        )
    return None


# --- modes -----------------------------------------------------------------------------------


def run_dump(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    manifest_path, _ = _paths(args)
    present = existing_backups(args.backup_dir)
    if manifest_path.exists() or present:
        print(
            f"REFUSED: a backup exists in {args.backup_dir} ({present or manifest_path.name}); "
            "a dump never overwrites",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    held = parse_held(args.hold)
    floor_gb, _ = rt.read_apr()
    free = shutil.disk_usage(args.disk_path).free
    with rt.connect() as conn:
        counts = plan_counts(conn, held)
        conn.rollback()
    for table, per_symbol in counts.items():
        print(f"{table}: {sum(per_symbol.values())} rows over {len(per_symbol)} symbols")
    print(f"held back: {held or 'none'}; free disk {free / _GIB:.1f} GiB, floor {floor_gb} GiB")
    if not args.apply:
        print("dry run: nothing written (add --apply to write the backup)")
        return EXIT_OK
    if free < floor_gb * _GIB:
        print("REFUSED: free disk below the APR floor", file=sys.stderr)
        return EXIT_REFUSED

    today = datetime.now(UTC).date()
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "created": datetime.now(UTC).isoformat(),
        "retention_until": RETENTION_UNTIL,
        "held": held,
        "tables": [],
    }
    with rt.connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            manifest["database"] = _scalar(conn, "SELECT current_database()")[0]
            off_raw, off_canonical = _scalar(conn, _OFF_TIMEFRAME_SQL)
            if off_raw or off_canonical:
                raise SystemExit(
                    f"REFUSED: Tradier bars outside 1d (raw {off_raw}, canonical "
                    f"{off_canonical}); the 1d-scoped predicates would miss them"
                )
            content = _digests(conn, held)
            manifest["retained_loads"] = int(_scalar(conn, _RETAINED_LOADS_SQL, {"held": held})[0])
            manifest["foreign_revisions"] = int(_scalar(conn, _FOREIGN_REVISIONS_SQL)[0])
            manifest["request_ledger"] = _ledger(conn)
            for spec in TABLES:
                path = args.backup_dir / backup_file_name(spec.table, today)
                with path.open("xb") as raw:
                    with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
                        with conn.cursor() as cur:
                            with cur.copy(
                                f"COPY ({spec.select_sql}) TO STDOUT (FORMAT csv)",
                                {"held": held},
                            ) as copy:
                                for block in copy:
                                    gz.write(bytes(block))
                    raw.flush()
                    os.fsync(raw.fileno())
                per_symbol = {s: n for s, (n, _md5) in content[spec.table].items()}
                rows = sum(per_symbol.values())
                records = count_csv_records(path)
                if records != rows:
                    raise SystemExit(f"{path.name}: {records} CSV records, count(*) {rows}")
                manifest["tables"].append(
                    {
                        "table": spec.table,
                        "predicate": spec.predicate,
                        "columns": _columns(conn, spec.table),
                        "rows": rows,
                        "per_symbol": per_symbol,
                        "per_symbol_md5": {s: md5 for s, (_n, md5) in content[spec.table].items()},
                        "file": path.name,
                        "sha256": sha256_of_file(path),
                        "bytes_on_disk": path.stat().st_size,
                    }
                )
                print(f"{spec.table}: {rows} rows -> {path.name}", flush=True)
    manifest["completed"] = datetime.now(UTC).isoformat()
    _fsync_dir(args.backup_dir)
    with manifest_path.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(args.backup_dir)
    print(f"manifest: {manifest_path} (retention until {RETENTION_UNTIL})")
    return EXIT_OK


def _verify_against_db(
    conn: psycopg.Connection, manifest: Mapping[str, Any], base: Path, completed: set[str]
) -> list[str]:
    held = list(manifest["held"])
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    with conn.transaction():
        live = plan_counts(conn, held)
        retained = int(_scalar(conn, _RETAINED_LOADS_SQL, {"held": held})[0])
        foreign = int(_scalar(conn, _FOREIGN_REVISIONS_SQL)[0])
        ledger = _ledger(conn)
    conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
    files: dict[str, int] = {}
    digests: dict[str, str] = {}
    for entry in manifest["tables"]:
        path = base / entry["file"]
        if path.exists():
            files[entry["table"]] = count_csv_records(path)
            digests[entry["table"]] = sha256_of_file(path)
    return verify_problems(
        manifest,
        live=live,
        files=files,
        digests=digests,
        completed=completed,
        retained_live=retained,
        foreign_revisions_live=foreign,
        ledger_live=ledger,
    )


def run_verify(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    manifest_path, state_path = _paths(args)
    manifest, digest = _load_manifest(manifest_path)
    if manifest is None:
        print(f"VERIFY FAILED: no manifest at {manifest_path}", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    _held_for(args, manifest)
    state = _load_state(state_path, digest)
    if state["manifest_sha256"] != digest:
        print("VERIFY FAILED: the delete state belongs to another manifest", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    completed = set(state["completed"])
    with rt.connect() as conn:
        flight = state.get("in_flight")
        if flight:
            # Read-only here: count the in-flight symbols as their live rows show, never save.
            settlement = settle(
                manifest,
                flight["symbols"],
                batch_counts(conn, flight["symbols"], manifest["held"]),
            )
            conn.rollback()
            if settlement.partial:
                print(f"VERIFY FAILED: partial in-flight {settlement.partial}", file=sys.stderr)
                return EXIT_VERIFY_FAILED
            completed |= set(settlement.committed)
        problems = _verify_against_db(conn, manifest, manifest_path.parent, completed)
    symbols = manifest_symbols(manifest)
    complete = set(symbols) <= completed
    report = {
        "manifest": str(manifest_path),
        "held_back": manifest["held"],
        "retained_tradier_loads": manifest["retained_loads"],
        "foreign_revisions": manifest["foreign_revisions"],
        "in_flight_unsettled": bool(state.get("in_flight")),
        "symbols_done": len(completed & set(symbols)),
        "symbols_total": len(symbols),
        "complete": complete,
        "problems": problems,
    }
    print(json.dumps(report, indent=2))
    if problems:
        print(f"VERIFY FAILED: {len(problems)} problem(s)", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    if args.require_complete and not complete:
        print("VERIFY FAILED: the delete is not complete", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    phase = (
        "deleted, zero Tradier rows remain"
        if complete
        else "live and backup-file row counts match the manifest (counts and file sha256 only; "
        "row content is compared per batch at delete time)"
    )
    print(f"verify ok: {phase}")
    return EXIT_OK


def _tsv_writer(rt: Runtime, held: Sequence[str]) -> Callable[[], None]:
    def write() -> None:
        rt.tsv_path.write_text(render_first_bar_tsv(rt.measure(), held))
        print(f"first-bar changes: {rt.tsv_path}", flush=True)

    return write


def run_trial(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    manifest_path, state_path = _paths(args)
    manifest, digest = _load_manifest(manifest_path)
    if manifest is None:
        print("REFUSED: no manifest; run --dump --apply first", file=sys.stderr)
        return EXIT_REFUSED
    held = _held_for(args, manifest)
    symbol = args.trial.strip().upper()
    state = _load_state(state_path, digest)
    if state["manifest_sha256"] != digest:
        print("REFUSED: the delete state belongs to another manifest", file=sys.stderr)
        return EXIT_REFUSED
    if symbol in held or symbol not in manifest_symbols(manifest):
        print(f"REFUSED: {symbol} is held back or has no Tradier rows", file=sys.stderr)
        return EXIT_REFUSED
    print(f"trial {symbol}: {expected_counts(manifest, [symbol])}")
    if not args.apply:
        print("dry run: nothing deleted (add --apply to run the trial)")
        return EXIT_OK
    floor_gb, _ = rt.read_apr()
    free_bytes = _free_reader(args.disk_path)
    with rt.connect() as conn:
        refusal = _settle_in_flight(
            conn, manifest, state, state_path, args.log_dir, free_bytes, digest
        )
        if refusal is not None:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return EXIT_REFUSED
        if symbol in state["completed"]:
            print(f"{symbol} is already deleted; nothing to trial", file=sys.stderr)
            return EXIT_REFUSED
        problems = _verify_against_db(conn, manifest, manifest_path.parent, set(state["completed"]))
        if problems:
            print(f"REFUSED: manifest does not verify: {problems}", file=sys.stderr)
            return EXIT_REFUSED
        flags = int(_scalar(conn, RESTATEMENT_FLAG_SQL, {"held": held})[0])
        conn.rollback()
        if flags:
            print(
                f"REFUSED: {flags} ohlcv_restatement_flag rows reference loads to delete",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        free_before = free_bytes()
        if free_before < floor_gb * _GIB:
            print("ABORT: free disk below the APR floor", file=sys.stderr)
            return EXIT_DISK_ABORT
        ensure_tsv(state, state_path, _tsv_writer(rt, held))
        started = datetime.now(UTC)
        _begin_flight(state, state_path, [symbol], free_before, trial=True)
        try:
            timings = delete_batch(
                conn,
                [symbol],
                held,
                expected_content(manifest, [symbol]),
                free_bytes=free_bytes,
                clock=time.monotonic,
            )
        except DeleteRefused as error:
            state["in_flight"] = None
            save_state(state, state_path)
            print(f"REFUSED (trial rolled back): {error}", file=sys.stderr)
            return EXIT_REFUSED
        free_after = free_bytes()
    state["completed"] = sorted(set(state["completed"]) | {symbol})
    state["in_flight"] = None
    state["batches"].append({"symbols": [symbol], "trial": True, "tables": timings})
    save_state(state, state_path)
    _write_trial_report(
        args.log_dir,
        {
            "symbol": symbol,
            "manifest_sha256": digest,
            "recovered": False,
            "started": started.isoformat(),
            "finished": datetime.now(UTC).isoformat(),
            "tables": timings,
            "rows_total": sum(t["rows"] for t in timings.values()),
            "seconds_total": round(sum(t["seconds"] for t in timings.values()), 3),
            "free_bytes_before": free_before,
            "free_bytes_after_commit": free_after,
            "disk_delta_bytes": free_before - free_after,
        },
    )
    return EXIT_OK


def run_delete(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    manifest_path, state_path = _paths(args)
    manifest, digest = _load_manifest(manifest_path)
    held = _held_for(args, manifest)
    if not args.apply:
        with rt.connect() as conn:
            counts = plan_counts(conn, held)
            conn.rollback()
        for table, per_symbol in counts.items():
            print(
                f"{table}: {sum(per_symbol.values())} rows to delete over {len(per_symbol)} symbols"
            )
        print(f"held back: {held or 'none'}; manifest: {'present' if manifest else 'missing'}")
        print("dry run: nothing deleted (add --apply to delete)")
        return EXIT_OK
    floor_gb, batch_symbols = rt.read_apr()
    state = _load_state(state_path, digest)
    free_bytes = _free_reader(args.disk_path)
    with rt.connect() as conn:
        flags = 0
        if manifest is not None and state["manifest_sha256"] == digest:
            refusal = _settle_in_flight(
                conn, manifest, state, state_path, args.log_dir, free_bytes, digest
            )
            if refusal is not None:
                print(f"REFUSED: {refusal}", file=sys.stderr)
                return EXIT_REFUSED
            flags = int(_scalar(conn, RESTATEMENT_FLAG_SQL, {"held": held})[0])
            conn.rollback()

        def _verify() -> list[str]:
            assert manifest is not None
            return _verify_against_db(conn, manifest, manifest_path.parent, set(state["completed"]))

        return apply_delete(
            conn=conn,
            manifest=manifest,
            manifest_sha256=digest,
            state=state,
            state_path=state_path,
            verify=_verify,
            trial_report=_latest_trial(args.log_dir, digest) if manifest else None,
            restatement_flags=flags,
            write_tsv=_tsv_writer(rt, held),
            batch_symbols=batch_symbols,
            floor_bytes=floor_gb * _GIB,
            free_bytes=free_bytes,
            clock=time.monotonic,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dump", action="store_true", help="COPY backup and manifest")
    mode.add_argument("--verify", action="store_true", help="manifest vs live and files")
    mode.add_argument("--trial", metavar="SYMBOL", help="delete one symbol, measure")
    mode.add_argument("--delete", action="store_true", help="gated batch delete")
    parser.add_argument("--apply", action="store_true", help="write; without it, report only")
    parser.add_argument("--hold", default=None, help="held-back symbols, comma separated (dump)")
    parser.add_argument(
        "--require-complete", action="store_true", help="--verify fails unless all deleted"
    )
    parser.add_argument("--backup-dir", type=Path, default=_BACKUP_DIR)
    parser.add_argument("--log-dir", type=Path, default=_LOG_DIR)
    parser.add_argument("--disk-path", type=Path, default=Path("/"))
    return parser


@contextmanager
def state_lock(log_dir: Path) -> Iterator[bool]:
    """An exclusive non-blocking flock beside the state file (the state file itself is replaced
    atomically, so the lock lives on a stable sibling); yields False when another run holds it."""
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / f"{_STATE_NAME}.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main(argv: Sequence[str] | None = None, rt: Runtime = PRODUCTION) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and (args.dump or args.trial or args.delete):
        with state_lock(args.log_dir) as acquired:
            if not acquired:
                print(
                    "REFUSED: another dump, trial or delete holds the state lock", file=sys.stderr
                )
                return EXIT_REFUSED
            return _run_mode(args, rt)
    return _run_mode(args, rt)


def _run_mode(args: argparse.Namespace, rt: Runtime) -> int:
    if args.dump:
        return run_dump(args, rt)
    if args.verify:
        return run_verify(args, rt)
    if args.trial:
        return run_trial(args, rt)
    return run_delete(args, rt)


if __name__ == "__main__":
    sys.exit(main())
