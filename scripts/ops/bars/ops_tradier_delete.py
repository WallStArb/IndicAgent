"""Tradier source-scoped deletion: backup, trial, batched delete, verify (phase 191 plan 20).

Design doc `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, "Owner exception: Tradier
deletion" and migration step 10; todo 533 Tradier retirement step 4. The owner ruled 2026-10-12
that Tradier is not used at all and its data is junk; after IBKR was asked for every span
Tradier covers and the residue was measured (plan 19), every Tradier value row is deleted,
behind a COPY backup kept until about 2026-11-12. Lineage stays: ohlcv_request (the fetch
ledger) and ohlcv_load (the write record, no bar values) keep their Tradier rows (design doc
amendment 2026-10-27), so the IBKR revision rows under Tradier loads stay by construction.

One exact predicate per value table, each excluding the held-back names the owner names at the
checkpoint (`--hold`, recorded in the manifest at `--dump` and read from it afterwards):

- ohlcv_revision: vendor = 'tradier' (old Tradier values, under any load);
- ohlcv_raw and market_data_ohlcv: vendor = 'tradier' and timeframe = '1d';
- ohlcv_coverage: provider = 'tradier'.

Modes (every write needs `--apply`; without it a mode reports and writes nothing; a write mode
holds an exclusive lock beside the state file and refuses while another run holds it):

- `--dump`: per table, `COPY (SELECT * FROM <table> WHERE <predicate>) TO STDOUT` into
  data/backups/191/tradier_<table>_<UTC date>.csv.gz inside one REPEATABLE READ transaction, and
  a manifest of per-(table, symbol) [row count, md5 over the ordered row text], each file's
  sha256 (hashed while written), the count of other-vendor revision rows under Tradier loads and
  the ohlcv_request counts. Each file's CSV records are recounted and must equal count(*). The
  dump never overwrites: it refuses while any tradier_* backup or the manifest exists, opens
  every file exclusively and fsyncs each file before the manifest is written.
- `--verify`: recounts the live Tradier rows per (table, symbol) and checks each backup file's
  sha256 (recounting its CSV records only when the hash differs) against the manifest; symbols
  the state records as done must hold zero rows. Also checks the other-vendor revision count,
  that the ohlcv_request Tradier count is unchanged and that its total has not shrunk.
  `--require-complete` additionally fails unless every symbol is deleted.
- `--trial SYMBOL`: writes the first-bar change TSV if not yet written, then deletes exactly one
  symbol's Tradier rows, timing each table and reading the free-disk delta, and writes
  logs/tradier_delete_trial_<SYMBOL>_<UTC>.json.
- `--delete`: refuses without a manifest, with a state bound to another manifest, with a
  manifest that does not verify, or without a fresh trial whose disk delta extrapolated over the
  remaining rows fits in the free space minus the APR floor. It writes the TSV if the trial did
  not, then deletes per symbol batch (APR `infra.tradier_delete.batch_symbols`); before every
  batch it reads free disk and stops (exit 3, state saved) below APR
  `infra.tradier_delete.min_free_disk_gb`.

Each batch is one REPEATABLE READ transaction across the four tables. Before any delete, each
(table, symbol) is recounted and its digest recomputed in that snapshot and must equal the
manifest; every DELETE's row count must then equal the batch's manifest total. Either refusal
rolls the batch back. Progress lives in logs/tradier_delete_state.json, bound to the manifest's
sha256. A batch's symbols are recorded as in flight before its transaction starts; a rerun after
a crash settles them by the live counts (zero in every table: committed, done; the manifest's
counts: rolled back, pending; anything else refuses), and a trial settled as committed gets a
recovered report, which the trial gate does not accept.

Why plain DELETE batches (plan amendment 2026-10-13): compressed_hypertable_write_session
(decompress=False included) is hardened for feature_vectors and feature_ic_scores only and
commits the caller's transaction, so it cannot hold a per-batch transaction here. The deletes
use TimescaleDB's native DML decompression (the per-transaction tuple limit is lifted inside
each batch). vendor is a segmentby column on ohlcv_raw, so its Tradier batches go whole; on
market_data_ohlcv the segmentby is (symbol, timeframe), so a Tradier delete decompresses the
name's 1d segments in every chunk it touches, and the decompressed survivors stay
uncompressed until the compression policy runs: that is what the trial measures. After the
run the operator issues bare `VACUUM ohlcv_raw;`, `VACUUM market_data_ohlcv;` and
`VACUUM ohlcv_revision;`.

The free disk is read at APR `infra.compressed_hypertable_write_session.disk_path` (the
filesystem holding the database volume) unless `--disk-path` overrides it. Sessions run with
statement_timeout 0, since the dump's scans and digests outlast the role's default timeout.

Table names in the SQL are unqualified and resolve through the session search_path: the
production connection refuses any schema list but ['public'], and the integration test points a
Runtime at a scratch schema on indicagent_test.

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

from scripts.ops.bars.ops_old_store_backup import (  # noqa: E402
    _HashingWriter,
    sha256_of_file,
)
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import get_settings  # noqa: E402

MIN_FREE_DISK_KEY = "infra.tradier_delete.min_free_disk_gb"
BATCH_SYMBOLS_KEY = "infra.tradier_delete.batch_symbols"
DISK_PATH_KEY = "infra.compressed_hypertable_write_session.disk_path"
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

# --- the one predicate per table ----------------------------------------------------------------

_HELD = "NOT (symbol = ANY(%(held)s::text[]))"
_BATCH = "symbol = ANY(%(batch)s::text[])"

_REVISION_PREDICATE = "vendor = 'tradier' AND " + _HELD
# timeframe is a segmentby column on both bar hypertables and vendor is not one on
# market_data_ohlcv: without it, a symbol-batch delete there decompresses every timeframe of the
# name (AAPL: 611k rows for 6.7k Tradier 1d rows). Every Tradier bar is 1d; the dump refuses
# while any Tradier bar of another timeframe exists (_OFF_TIMEFRAME_SQL), so the predicate stays
# exact.
_BAR_1D_PREDICATE = "vendor = 'tradier' AND timeframe = '1d' AND " + _HELD
_COVERAGE_PREDICATE = "provider = 'tradier' AND " + _HELD

# Each DELETE names its table in the source text, so the single-writer boundary tests find it.
_DELETE_REVISION_SQL = "DELETE FROM ohlcv_revision WHERE " + _BATCH + " AND " + _REVISION_PREDICATE
_DELETE_RAW_SQL = "DELETE FROM ohlcv_raw WHERE " + _BATCH + " AND " + _BAR_1D_PREDICATE
_DELETE_CANONICAL_SQL = (
    "DELETE FROM market_data_ohlcv WHERE " + _BATCH + " AND " + _BAR_1D_PREDICATE
)
_DELETE_COVERAGE_SQL = "DELETE FROM ohlcv_coverage WHERE " + _BATCH + " AND " + _COVERAGE_PREDICATE


@dataclass(frozen=True)
class TableSpec:
    table: str
    predicate: str
    delete_sql: str

    def _count_sql(self, where: str) -> str:
        return f"SELECT symbol, count(*) FROM {self.table} WHERE {where} GROUP BY symbol"

    def _digest_sql(self, where: str) -> str:
        # The whole-row text of every selected row, ordered by that text, so the digest depends
        # on content only. Sessions run with timezone UTC, so timestamps render the same way.
        row = f"{self.table}::text"
        return (
            f"SELECT symbol, count(*), md5(string_agg({row}, E'\\n' ORDER BY {row})) "
            f"FROM {self.table} WHERE {where} GROUP BY symbol"
        )

    @property
    def count_sql(self) -> str:
        return self._count_sql(self.predicate)

    @property
    def batch_count_sql(self) -> str:
        return self._count_sql(f"{_BATCH} AND {self.predicate}")

    @property
    def digest_sql(self) -> str:
        return self._digest_sql(self.predicate)

    @property
    def batch_digest_sql(self) -> str:
        return self._digest_sql(f"{_BATCH} AND {self.predicate}")

    @property
    def select_sql(self) -> str:
        return f"SELECT * FROM {self.table} WHERE {self.predicate}"


# Delete order inside a batch; it is also the restore order (no foreign keys between them).
TABLES: tuple[TableSpec, ...] = (
    TableSpec("ohlcv_revision", _REVISION_PREDICATE, _DELETE_REVISION_SQL),
    TableSpec("ohlcv_raw", _BAR_1D_PREDICATE, _DELETE_RAW_SQL),
    TableSpec("market_data_ohlcv", _BAR_1D_PREDICATE, _DELETE_CANONICAL_SQL),
    TableSpec("ohlcv_coverage", _COVERAGE_PREDICATE, _DELETE_COVERAGE_SQL),
)
SPECS: dict[str, TableSpec] = {spec.table: spec for spec in TABLES}

DECOMPRESSION_LIMIT_SQL = "SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0"

# Other-vendor revision rows under Tradier loads (3,179,829 ibkr rows on 2026-10-27): IBKR
# evidence that stays; it must not move (T-191-45).
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


def count_csv_records(path: Path) -> int:
    """CSV records in a gzip file, parsed (a quoted field may hold a newline)."""
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        return sum(1 for _ in csv.reader(stream))


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_backup_files(
    manifest: Mapping[str, Any], base: Path
) -> tuple[dict[str, int], dict[str, str]]:
    """Per table, the file's record count and sha256. A file whose hash equals the manifest's
    holds the manifest's bytes, so its records are recounted only when the hash differs."""
    files: dict[str, int] = {}
    digests: dict[str, str] = {}
    for entry in manifest["tables"]:
        path = base / entry["file"]
        if not path.exists():
            continue
        digest = sha256_of_file(path)
        digests[entry["table"]] = digest
        files[entry["table"]] = (
            table_rows(entry) if digest == entry["sha256"] else count_csv_records(path)
        )
    return files, digests


# --- the manifest ----------------------------------------------------------------------------


def table_rows(entry: Mapping[str, Any]) -> int:
    return sum(int(n) for n, _md5 in entry["per_symbol"].values())


def manifest_symbols(manifest: Mapping[str, Any]) -> list[str]:
    return sorted({s for t in manifest["tables"] for s in t["per_symbol"]})


def expected_content(
    manifest: Mapping[str, Any], batch: Sequence[str]
) -> dict[str, dict[str, tuple[int, str]]]:
    """table -> symbol -> (row count, md5) for the batch's symbols holding rows there."""
    return {
        t["table"]: {
            s: (int(t["per_symbol"][s][0]), t["per_symbol"][s][1])
            for s in batch
            if s in t["per_symbol"]
        }
        for t in manifest["tables"]
    }


def expected_counts(manifest: Mapping[str, Any], batch: Sequence[str]) -> dict[str, int]:
    return {
        table: sum(n for n, _md5 in content.values())
        for table, content in expected_content(manifest, batch).items()
    }


def verify_problems(
    manifest: Mapping[str, Any],
    *,
    live: Mapping[str, Mapping[str, int]],
    files: Mapping[str, int],
    digests: Mapping[str, str],
    completed: set[str],
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
        recorded = {s: int(v[0]) for s, v in entry["per_symbol"].items()}
        observed = live.get(table, {})
        for symbol in sorted(set(recorded) | set(observed)):
            want = 0 if symbol in completed else recorded.get(symbol, 0)
            have = int(observed.get(symbol, 0))
            if have != want:
                problems.append(f"{table} {symbol}: live {have} != expected {want}")
        rows = table_rows(entry)
        if table not in files:
            problems.append(f"{table}: file {entry['file']} missing")
        elif files[table] != rows:
            problems.append(f"{table}: file rows {files[table]} != manifest {rows}")
        if table in digests and digests[table] != entry["sha256"]:
            problems.append(f"{table}: sha256 of {entry['file']} changed")
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
            (int(t["per_symbol"].get(symbol, [0])[0]), int(live.get(t["table"], {}).get(symbol, 0)))
            for t in manifest["tables"]
        ]
        if all(have == 0 for _, have in pairs):
            out.committed.append(symbol)
        elif all(have == want for want, have in pairs):
            out.rolled_back.append(symbol)
        else:
            out.partial.append(symbol)
    return out


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


def _trial_report(
    symbol: str,
    manifest_sha256: str,
    *,
    recovered: bool,
    started: str,
    tables: Mapping[str, Any] | None,
    rows_total: int,
    free_before: int,
    free_after: int,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "manifest_sha256": manifest_sha256,
        "recovered": recovered,
        "started": started,
        "finished": datetime.now(UTC).isoformat(),
        "tables": dict(tables) if tables is not None else None,
        "rows_total": rows_total,
        "seconds_total": (
            round(sum(t["seconds"] for t in tables.values()), 3) if tables is not None else None
        ),
        "free_bytes_before": free_before,
        "free_bytes_after_commit": free_after,
        "disk_delta_bytes": free_before - free_after,
    }


def _write_trial_report(log_dir: Path, report: Mapping[str, Any]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"{_TRIAL_PREFIX}{report['symbol']}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"trial report: {path}")
    return path


# --- one batch -------------------------------------------------------------------------------


@contextmanager
def repeatable_read(conn: Any) -> Iterator[None]:
    """One REPEATABLE READ transaction; the connection returns to READ COMMITTED however the
    block ends."""
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    try:
        with conn.transaction():
            yield
    finally:
        conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED


def delete_batch(
    conn: Any,
    batch: Sequence[str],
    held: Sequence[str],
    expected: Mapping[str, Mapping[str, tuple[int, str]]],
    *,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> dict[str, dict[str, Any]]:
    """Delete one symbol batch from the four tables in one REPEATABLE READ transaction.

    Before any delete, each (table, symbol) is recounted and its digest recomputed in the
    snapshot and must equal the manifest; then every DELETE's row count must equal the batch's
    manifest total. Any difference raises DeleteRefused and rolls the whole batch back.
    """
    params = {"batch": list(batch), "held": list(held)}
    timings: dict[str, dict[str, Any]] = {}
    with repeatable_read(conn), conn.cursor() as cur:
        cur.execute(DECOMPRESSION_LIMIT_SQL)
        for spec in TABLES:
            cur.execute(spec.batch_digest_sql, params)
            found = {s: (int(n), md5) for s, n, md5 in cur.fetchall()}
            want = dict(expected[spec.table])
            if found != want:
                differing = sorted(s for s in set(found) | set(want) if found.get(s) != want.get(s))
                raise DeleteRefused(
                    f"batch {list(batch)}: {spec.table} content differs from the manifest "
                    f"for {differing}"
                )
        for spec in TABLES:
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


def _run_one_batch(
    conn: Any,
    manifest: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    batch: Sequence[str],
    free: int,
    *,
    trial: bool,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> dict[str, dict[str, Any]]:
    """In flight, delete, done: the one path for the trial and every batch. A refusal clears the
    in-flight record (the batch rolled back) and re-raises."""
    state["in_flight"] = {
        "symbols": list(batch),
        "trial": trial,
        "free_bytes_before": free,
        "started": datetime.now(UTC).isoformat(),
    }
    save_state(state, state_path)
    try:
        timings = delete_batch(
            conn,
            batch,
            manifest["held"],
            expected_content(manifest, batch),
            free_bytes=free_bytes,
            clock=clock,
        )
    except DeleteRefused:
        state["in_flight"] = None
        save_state(state, state_path)
        raise
    state["completed"] = sorted(set(state["completed"]) | set(batch))
    state["in_flight"] = None
    state["batches"].append(
        {"symbols": list(batch), "trial": trial, "free_bytes_before": free, "tables": timings}
    )
    save_state(state, state_path)
    return timings


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
                f"{len(state['completed'])} symbols done, {len(pending) - start} left",
                file=sys.stderr,
            )
            return EXIT_DISK_ABORT
        try:
            timings = _run_one_batch(
                conn,
                manifest,
                state,
                state_path,
                batch,
                free,
                trial=False,
                free_bytes=free_bytes,
                clock=clock,
            )
        except DeleteRefused as error:
            state["aborted"] = {
                "reason": str(error),
                "next_batch": batch,
                "at": datetime.now(UTC).isoformat(),
            }
            save_state(state, state_path)
            print(f"REFUSED (batch rolled back): {error}", file=sys.stderr)
            return EXIT_REFUSED
        print(
            f"batch {start // batch_symbols + 1}: {len(batch)} symbols, "
            f"{sum(t['rows'] for t in timings.values())} rows; "
            f"{len(state['completed'])} done",
            flush=True,
        )
    return EXIT_OK


def apply_delete(
    *,
    conn: Any,
    manifest: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    verify: Callable[[], list[str]],
    trial_report: Mapping[str, Any] | None,
    write_tsv: Callable[[], None],
    batch_symbols: int,
    floor_bytes: int,
    free_bytes: Callable[[], int],
    clock: Callable[[], float],
) -> int:
    """The gated batch delete: verify, trial, TSV, then the batches. The caller has refused a
    missing or mismatched manifest and settled any in-flight batch."""
    problems = verify()
    if problems:
        print(f"REFUSED: manifest does not verify ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_REFUSED
    done = set(state["completed"])
    remaining = sum(
        int(v[0])
        for t in manifest["tables"]
        for symbol, v in t["per_symbol"].items()
        if symbol not in done
    )
    refusal = trial_refusal(trial_report, remaining, free_bytes(), floor_bytes)
    if refusal is not None:
        print(f"REFUSED: {refusal}", file=sys.stderr)
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


# --- per-table reads -------------------------------------------------------------------------


def _per_table(
    conn: Any, sql_of: Callable[[TableSpec], str], params: Mapping[str, Any]
) -> dict[str, list[tuple[Any, ...]]]:
    rows: dict[str, list[tuple[Any, ...]]] = {}
    with conn.cursor() as cur:
        for spec in TABLES:
            cur.execute(sql_of(spec), dict(params))
            rows[spec.table] = list(cur.fetchall())
    return rows


def plan_counts(conn: Any, held: Sequence[str]) -> dict[str, dict[str, int]]:
    """Per-table, per-symbol Tradier row counts under the predicates; SELECTs only."""
    rows = _per_table(conn, lambda spec: spec.count_sql, {"held": list(held)})
    return {table: {s: int(n) for s, n in found} for table, found in rows.items()}


def batch_counts(conn: Any, batch: Sequence[str], held: Sequence[str]) -> dict[str, dict[str, int]]:
    """plan_counts restricted to a batch of symbols (the in-flight settlement read)."""
    rows = _per_table(
        conn, lambda spec: spec.batch_count_sql, {"batch": list(batch), "held": list(held)}
    )
    return {table: {s: int(n) for s, n in found} for table, found in rows.items()}


def _digests(conn: Any, held: Sequence[str]) -> dict[str, dict[str, list[Any]]]:
    rows = _per_table(conn, lambda spec: spec.digest_sql, {"held": list(held)})
    return {table: {s: [int(n), md5] for s, n, md5 in found} for table, found in rows.items()}


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


async def _read_apr_async() -> tuple[int, int, str]:
    cfg = ConfigService(get_settings().database_url)
    await cfg.initialize()
    try:
        floor_gb = int(await cfg.get(MIN_FREE_DISK_KEY, 200))
        batch = int(await cfg.get(BATCH_SYMBOLS_KEY, 20))
        disk_path = str(await cfg.get(DISK_PATH_KEY, "/"))
    finally:
        await cfg.close()
    return floor_gb, batch, disk_path


def _read_apr() -> tuple[int, int, str]:
    return asyncio.run(_read_apr_async())


@dataclass(frozen=True)
class Runtime:
    """Where the script reads and writes: the database connection, the APR values (floor GiB,
    batch symbols, disk path), the first-bar measurement and the TSV path."""

    connect: Callable[[], psycopg.Connection]
    read_apr: Callable[[], tuple[int, int, str]]
    measure: Callable[[], list[dict[str, Any]]]
    tsv_path: Path


PRODUCTION = Runtime(
    connect=_connect, read_apr=_read_apr, measure=_measure_first_bars, tsv_path=_TSV_PATH
)


# --- plumbing --------------------------------------------------------------------------------


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


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    return args.backup_dir / _MANIFEST_NAME, args.log_dir / _STATE_NAME


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.exists():
        return None, ""
    text = path.read_text()
    return json.loads(text), hashlib.sha256(text.encode()).hexdigest()


def _load_state(path: Path, manifest_sha256: str) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else new_state(manifest_sha256)


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


def disk_path_for(args: argparse.Namespace, apr_disk_path: str) -> Path:
    return args.disk_path if args.disk_path is not None else Path(apr_disk_path)


def _free_reader(path: Path) -> Callable[[], int]:
    return lambda: shutil.disk_usage(path).free


def _bound_manifest(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str, dict[str, Any], Path] | str:
    """The manifest, its sha256, the state and the state path; or a refusal when the manifest is
    missing or the state belongs to another manifest."""
    manifest_path, state_path = _paths(args)
    manifest, digest = _load_manifest(manifest_path)
    if manifest is None:
        return f"no manifest at {manifest_path}; run --dump --apply first"
    state = _load_state(state_path, digest)
    if state["manifest_sha256"] != digest:
        return "the delete state belongs to another manifest"
    return manifest, digest, state, state_path


def _settle_in_flight(
    conn: Any,
    manifest: Mapping[str, Any],
    state: dict[str, Any],
    state_path: Path,
    log_dir: Path,
    free_bytes: Callable[[], int],
    digest: str,
) -> str | None:
    """Settles a crashed run's in-flight batch from the live counts and saves the state; a
    committed trial gets its recovered report. Returns a refusal for a partial symbol, leaving
    the in-flight record in place."""
    flight = state.get("in_flight")
    if not flight:
        return None
    symbols = list(flight["symbols"])
    settlement = settle(manifest, symbols, batch_counts(conn, symbols, list(manifest["held"])))
    conn.rollback()
    if settlement.partial:
        return (
            f"in-flight symbols {settlement.partial} are partly deleted; the live rows match "
            "neither the manifest nor zero"
        )
    state["completed"] = sorted(set(state["completed"]) | set(settlement.committed))
    state["in_flight"] = None
    save_state(state, state_path)
    print(
        f"settled in-flight batch: committed {settlement.committed}, "
        f"rolled back {settlement.rolled_back}"
    )
    if flight.get("trial") and settlement.committed:
        symbol = settlement.committed[0]
        _write_trial_report(
            log_dir,
            _trial_report(
                symbol,
                digest,
                recovered=True,
                started=flight["started"],
                tables=None,
                rows_total=sum(expected_counts(manifest, [symbol]).values()),
                free_before=int(flight["free_bytes_before"]),
                free_after=free_bytes(),
            ),
        )
    return None


# --- modes -----------------------------------------------------------------------------------


def run_dump(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    manifest_path, _ = _paths(args)
    present = (
        sorted(p.name for p in args.backup_dir.glob(_BACKUP_GLOB))
        if args.backup_dir.exists()
        else []
    )
    if manifest_path.exists() or present:
        print(
            f"REFUSED: a backup exists in {args.backup_dir} ({present or manifest_path.name}); "
            "a dump never overwrites",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    held = parse_held(args.hold)
    floor_gb, _, apr_disk_path = rt.read_apr()
    free = shutil.disk_usage(disk_path_for(args, apr_disk_path)).free
    print(f"held back: {held or 'none'}; free disk {free / _GIB:.1f} GiB, floor {floor_gb} GiB")
    if not args.apply:
        with rt.connect() as conn:
            counts = plan_counts(conn, held)
            conn.rollback()
        for table, per_symbol in counts.items():
            print(f"{table}: {sum(per_symbol.values())} rows over {len(per_symbol)} symbols")
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
    with rt.connect() as conn, repeatable_read(conn):
        manifest["database"] = _scalar(conn, "SELECT current_database()")[0]
        off_raw, off_canonical = _scalar(conn, _OFF_TIMEFRAME_SQL)
        if off_raw or off_canonical:
            raise SystemExit(
                f"REFUSED: Tradier bars outside 1d (raw {off_raw}, canonical "
                f"{off_canonical}); the 1d-scoped predicates would miss them"
            )
        content = _digests(conn, held)
        manifest["foreign_revisions"] = int(_scalar(conn, _FOREIGN_REVISIONS_SQL)[0])
        manifest["request_ledger"] = _ledger(conn)
        for spec in TABLES:
            path = args.backup_dir / backup_file_name(spec.table, today)
            with path.open("xb") as raw:
                writer = _HashingWriter(raw)
                with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=6, mtime=0) as gz:
                    with conn.cursor() as cur:
                        with cur.copy(
                            f"COPY ({spec.select_sql}) TO STDOUT (FORMAT csv)", {"held": held}
                        ) as copy:
                            for block in copy:
                                gz.write(bytes(block))
                raw.flush()
                os.fsync(raw.fileno())
            entry = {
                "table": spec.table,
                "predicate": spec.predicate,
                "columns": _columns(conn, spec.table),
                "per_symbol": content[spec.table],
                "file": path.name,
                "sha256": writer.sha256,
                "bytes_on_disk": writer.bytes_on_disk,
            }
            rows = table_rows(entry)
            records = count_csv_records(path)
            if records != rows:
                raise SystemExit(f"{path.name}: {records} CSV records, count(*) {rows}")
            manifest["tables"].append(entry)
            print(
                f"{spec.table}: {rows} rows over {len(entry['per_symbol'])} symbols -> "
                f"{path.name}",
                flush=True,
            )
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
    conn: Any, manifest: Mapping[str, Any], base: Path, completed: set[str]
) -> list[str]:
    with repeatable_read(conn):
        live = plan_counts(conn, manifest["held"])
        foreign = int(_scalar(conn, _FOREIGN_REVISIONS_SQL)[0])
        ledger = _ledger(conn)
    files, digests = read_backup_files(manifest, base)
    return verify_problems(
        manifest,
        live=live,
        files=files,
        digests=digests,
        completed=completed,
        foreign_revisions_live=foreign,
        ledger_live=ledger,
    )


def run_verify(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    bound = _bound_manifest(args)
    if isinstance(bound, str):
        print(f"VERIFY FAILED: {bound}", file=sys.stderr)
        return EXIT_VERIFY_FAILED
    manifest, _digest, state, _state_path = bound
    _held_for(args, manifest)
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
        problems = _verify_against_db(conn, manifest, args.backup_dir, completed)
    symbols = manifest_symbols(manifest)
    complete = set(symbols) <= completed
    report = {
        "manifest": str(args.backup_dir / _MANIFEST_NAME),
        "held_back": manifest["held"],
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
    bound = _bound_manifest(args)
    if isinstance(bound, str):
        print(f"REFUSED: {bound}", file=sys.stderr)
        return EXIT_REFUSED
    manifest, digest, state, state_path = bound
    held = _held_for(args, manifest)
    symbol = args.trial.strip().upper()
    if symbol in held or symbol not in manifest_symbols(manifest):
        print(f"REFUSED: {symbol} is held back or has no Tradier rows", file=sys.stderr)
        return EXIT_REFUSED
    print(f"trial {symbol}: {expected_counts(manifest, [symbol])}")
    if not args.apply:
        print("dry run: nothing deleted (add --apply to run the trial)")
        return EXIT_OK
    floor_gb, _, apr_disk_path = rt.read_apr()
    free_bytes = _free_reader(disk_path_for(args, apr_disk_path))
    with rt.connect() as conn:
        refusal = _settle_in_flight(
            conn, manifest, state, state_path, args.log_dir, free_bytes, digest
        )
        if refusal is not None:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return EXIT_REFUSED
        if symbol in state["completed"]:
            print(f"REFUSED: {symbol} is already deleted; nothing to trial", file=sys.stderr)
            return EXIT_REFUSED
        problems = _verify_against_db(conn, manifest, args.backup_dir, set(state["completed"]))
        if problems:
            print(f"REFUSED: manifest does not verify: {problems}", file=sys.stderr)
            return EXIT_REFUSED
        free_before = free_bytes()
        if free_before < floor_gb * _GIB:
            print("ABORT: free disk below the APR floor", file=sys.stderr)
            return EXIT_DISK_ABORT
        ensure_tsv(state, state_path, _tsv_writer(rt, held))
        started = datetime.now(UTC).isoformat()
        try:
            timings = _run_one_batch(
                conn,
                manifest,
                state,
                state_path,
                [symbol],
                free_before,
                trial=True,
                free_bytes=free_bytes,
                clock=time.monotonic,
            )
        except DeleteRefused as error:
            print(f"REFUSED (trial rolled back): {error}", file=sys.stderr)
            return EXIT_REFUSED
        free_after = free_bytes()
    _write_trial_report(
        args.log_dir,
        _trial_report(
            symbol,
            digest,
            recovered=False,
            started=started,
            tables=timings,
            rows_total=sum(t["rows"] for t in timings.values()),
            free_before=free_before,
            free_after=free_after,
        ),
    )
    return EXIT_OK


def run_delete(args: argparse.Namespace, rt: Runtime = PRODUCTION) -> int:
    if not args.apply:
        manifest, _ = _load_manifest(_paths(args)[0])
        held = _held_for(args, manifest)
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
    bound = _bound_manifest(args)
    if isinstance(bound, str):
        print(f"REFUSED: {bound}", file=sys.stderr)
        return EXIT_REFUSED
    manifest, digest, state, state_path = bound
    _held_for(args, manifest)
    floor_gb, batch_symbols, apr_disk_path = rt.read_apr()
    free_bytes = _free_reader(disk_path_for(args, apr_disk_path))
    with rt.connect() as conn:
        refusal = _settle_in_flight(
            conn, manifest, state, state_path, args.log_dir, free_bytes, digest
        )
        if refusal is not None:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return EXIT_REFUSED
        return apply_delete(
            conn=conn,
            manifest=manifest,
            state=state,
            state_path=state_path,
            verify=lambda: _verify_against_db(
                conn, manifest, args.backup_dir, set(state["completed"])
            ),
            trial_report=_latest_trial(args.log_dir, digest),
            write_tsv=_tsv_writer(rt, manifest["held"]),
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
    parser.add_argument(
        "--disk-path", type=Path, default=None, help=f"default: APR {DISK_PATH_KEY}"
    )
    return parser


def _run_mode(args: argparse.Namespace, rt: Runtime) -> int:
    if args.dump:
        return run_dump(args, rt)
    if args.verify:
        return run_verify(args, rt)
    if args.trial:
        return run_trial(args, rt)
    return run_delete(args, rt)


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


if __name__ == "__main__":
    sys.exit(main())
