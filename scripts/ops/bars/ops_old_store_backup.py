"""COPY backup of the two old bar stores (phase 191 plan 16, design doc step 8).

`--dump` writes, per table, one gzip CSV file per year slice of the table's date column
(`bar_date` for ohlcv_observation, `timestamp` for ohlcv_intraday_raw_archive) into
data/backups/191/, streaming `COPY (SELECT * FROM <table> WHERE <slice>) TO STDOUT`
through one serial connection inside a single REPEATABLE READ transaction, plus a manifest
JSON (table, file, row count, sha256) beside the files. `--verify` recounts every year
slice live inside one REPEATABLE READ transaction, counts the rows of each file by reading
it back, and checks each file's sha256; any mismatch exits nonzero naming the slice.
`--verify-files` does the file half only (row recount and sha256 against the manifest,
no database read): since migration 499 dropped both tables, it is the retention-period
check for the backup sitting on disk.

The script never removes anything and never writes to the database: its only statements are
SELECT, COPY ... TO STDOUT and catalog reads. A dump refuses to start when the free space on
the backup volume is below the estimated output (the tables' total relation size) times the
APR key `infra.old_store_backup.disk_margin` (seeded by migration 498, default 2).

CSV row counting assumes no value renders with an embedded newline: every column of both
tables is a uuid, date, timestamp, number or short uppercase token, and a file that does not
end in a newline is refused loudly rather than miscounted.

TEMPORARY: kept to the backup retention date 2026-11-12 (the 185-45 backup precedent, todo
510); plan 17 records the date and plan 18 deletes this script with the backup files.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, BinaryIO

import psycopg

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import get_settings  # noqa: E402

DISK_MARGIN_KEY = "infra.old_store_backup.disk_margin"
RETENTION_UNTIL = "2026-11-12"
_DEFAULT_BACKUP_DIR = project_root / "data" / "backups" / "191"
_DEFAULT_MANIFEST = "old_store_backup_manifest.json"


@dataclass(frozen=True)
class TableSpec:
    table: str
    date_column: str
    # "date" columns bound by an ISO date literal; "timestamptz" columns bound by an explicit
    # UTC instant, so no session timezone can move a slice boundary.
    bound_kind: str


TABLES: tuple[TableSpec, ...] = (
    TableSpec("ohlcv_observation", "bar_date", "date"),
    TableSpec("ohlcv_intraday_raw_archive", '"timestamp"', "timestamptz"),
)


@dataclass(frozen=True)
class YearSlice:
    year: int
    lo: date
    hi: date


@dataclass
class SliceFile:
    year: int
    path: Path
    rows: int
    sha256: str
    bytes_on_disk: int
    csv_bytes: int


def year_slices(first_year: int, last_year: int) -> list[YearSlice]:
    """Half-open calendar-year slices [year-01-01, year+1-01-01) covering both ends."""
    return [
        YearSlice(year, date(year, 1, 1), date(year + 1, 1, 1))
        for year in range(first_year, last_year + 1)
    ]


def _bound(day: date, kind: str) -> str:
    if kind == "date":
        return day.isoformat()
    return f"{day.isoformat()}T00:00:00+00:00"


def slice_select_sql(spec: TableSpec, lo: date, hi: date) -> str:
    return (
        f"SELECT * FROM {spec.table} WHERE {spec.date_column} >= "
        f"'{_bound(lo, spec.bound_kind)}' AND {spec.date_column} < '{_bound(hi, spec.bound_kind)}'"
    )


class _HashingWriter:
    """A raw-file stand-in that hashes and sizes the compressed bytes as gzip writes them."""

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self._hash = hashlib.sha256()
        self.bytes_on_disk = 0

    def write(self, data: bytes) -> int:
        self._hash.update(data)
        self.bytes_on_disk += len(data)
        return self._raw.write(data)

    def tell(self) -> int:  # gzip.GzipFile calls this
        return self.bytes_on_disk

    def flush(self) -> None:
        self._raw.flush()

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()


def count_rows_in_file(path: Path) -> int:
    """Rows of a gzip CSV written by this script: newline count, with the final-newline guard.

    Empty files (zero-row slices are never written, but a truncated dump may leave one) count
    as zero; a non-empty file whose last byte is not a newline refuses rather than miscount.
    """
    rows = 0
    last = b""
    with gzip.open(path, "rb") as stream:
        while block := stream.read(1 << 20):
            rows += block.count(b"\n")
            last = block[-1:]
    if rows and last != b"\n":
        raise ValueError(f"{path.name}: stream does not end in a final newline; not countable")
    return rows


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def manifest_table_totals(manifest: dict[str, Any]) -> dict[str, int]:
    return {
        table["table"]: sum(int(f["rows"]) for f in table["files"]) for table in manifest["tables"]
    }


def verify_slices(
    manifest: dict[str, Any],
    live: dict[tuple[str, int], int],
    files: dict[tuple[str, int], int],
    digests: dict[tuple[str, int], str],
) -> list[str]:
    """Every disagreement between the manifest, the live database and the files on disk,
    one message per slice and aspect, naming the table and the year."""
    problems: list[str] = []
    recorded: set[tuple[str, int]] = set()
    for table in manifest["tables"]:
        name = table["table"]
        for entry in table["files"]:
            year, rows = int(entry["year"]), int(entry["rows"])
            recorded.add((name, year))
            key = (name, year)
            if key not in live:
                problems.append(f"{name} {year}: live count missing; manifest holds {rows}")
            elif live[key] != rows:
                problems.append(f"{name} {year}: live count {live[key]} != manifest {rows}")
            if key not in files:
                problems.append(f"{name} {year}: file {entry['file']} missing")
            elif files[key] != rows:
                problems.append(f"{name} {year}: file rows {files[key]} != manifest {rows}")
            if key not in digests:
                problems.append(f"{name} {year}: digest of {entry['file']} missing")
            elif digests[key] != entry["sha256"]:
                problems.append(f"{name} {year}: sha256 of {entry['file']} changed")
    for key in sorted(set(live) - recorded):
        problems.append(f"{key[0]} {key[1]}: live count {live[key]} not in the manifest")
    return problems


def verify_files(
    manifest: dict[str, Any],
    files: dict[tuple[str, int], int],
    digests: dict[tuple[str, int], str],
) -> list[str]:
    """Every disagreement between the manifest and the files on disk, one message per
    slice and aspect, naming the table and the year; no database involved."""
    problems: list[str] = []
    for table in manifest["tables"]:
        name = table["table"]
        for entry in table["files"]:
            year, rows = int(entry["year"]), int(entry["rows"])
            key = (name, year)
            if key not in files:
                problems.append(f"{name} {year}: file {entry['file']} missing")
            elif files[key] != rows:
                problems.append(f"{name} {year}: file rows {files[key]} != manifest {rows}")
            if key not in digests:
                problems.append(f"{name} {year}: digest of {entry['file']} missing")
            elif digests[key] != entry["sha256"]:
                problems.append(f"{name} {year}: sha256 of {entry['file']} changed")
    return problems


def disk_refusal(free_bytes: int, estimated_bytes: int, margin: float) -> str | None:
    """A refusal message when free space is below estimate * margin, else None."""
    if margin < 1.0:
        raise ValueError(f"disk margin must be >= 1.0, got {margin}")
    required = int(estimated_bytes * margin)
    if free_bytes < required:
        return (
            f"free {free_bytes} bytes is below the estimated output {estimated_bytes} "
            f"bytes times margin {margin} ({required} bytes); refusing to start the dump"
        )
    return None


async def read_margin() -> int:
    cfg = ConfigService(get_settings().database_url)
    await cfg.initialize()
    try:
        return int(await cfg.get(DISK_MARGIN_KEY, 2))
    finally:
        await cfg.close()


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        get_settings().database_url,
        options="-c timezone=UTC",
        autocommit=False,
    )


def _year_range(cur: psycopg.Cursor, spec: TableSpec) -> tuple[int, int]:
    cur.execute(
        f"SELECT extract(year from min({spec.date_column}))::int, "
        f"extract(year from max({spec.date_column}))::int FROM {spec.table}"
    )
    first, last = cur.fetchone()
    if first is None:
        raise SystemExit(f"{spec.table}: no rows to back up")
    return first, last


def _columns(cur: psycopg.Cursor, spec: TableSpec) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (spec.table,),
    )
    return [row[0] for row in cur.fetchall()]


def _dump_slice(
    cur: psycopg.Cursor, spec: TableSpec, sl: YearSlice, out_dir: Path
) -> SliceFile | None:
    select_sql = slice_select_sql(spec, sl.lo, sl.hi)
    cur.execute(f"SELECT count(*) FROM ({select_sql}) c")
    rows_expected = cur.fetchone()[0]
    if rows_expected == 0:
        return None
    path = out_dir / f"{spec.table}_{sl.year}.csv.gz"
    rows_written = 0
    csv_bytes = 0
    last = b""
    with path.open("wb") as raw:
        writer = _HashingWriter(raw)
        with gzip.GzipFile(fileobj=writer, mode="wb", compresslevel=6, mtime=0) as zipped:
            with cur.copy(f"COPY ({select_sql}) TO STDOUT (FORMAT csv)") as copy:
                for block in copy:
                    data = bytes(block)
                    rows_written += data.count(b"\n")
                    csv_bytes += len(data)
                    last = data[-1:]
                    zipped.write(data)
    if rows_written and last != b"\n":
        raise SystemExit(f"{path.name}: COPY stream did not end in a final newline; dump refused")
    if rows_written != rows_expected:
        raise SystemExit(f"{path.name}: wrote {rows_written} rows, expected {rows_expected}")
    return SliceFile(
        year=sl.year,
        path=path,
        rows=rows_written,
        sha256=writer.sha256,
        bytes_on_disk=writer.bytes_on_disk,
        csv_bytes=csv_bytes,
    )


def run_dump(out_dir: Path, manifest_path: Path) -> int:
    margin = asyncio.run(read_margin())
    out_dir.mkdir(parents=True, exist_ok=True)
    estimated = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for spec in TABLES:
                cur.execute("SELECT pg_total_relation_size(%s)", (spec.table,))
                estimated += cur.fetchone()[0]
        conn.rollback()
    refusal = disk_refusal(shutil.disk_usage(out_dir).free, estimated, margin)
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return 2

    started = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "created": started.isoformat(),
        "database": get_settings().database_url.rsplit("/", 1)[-1],
        "retention_until": RETENTION_UNTIL,
        "disk_margin": margin,
        "estimated_bytes": estimated,
        "tables": [],
    }
    with _connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            with conn.cursor() as cur:
                for spec in TABLES:
                    first, last = _year_range(cur, spec)
                    columns = _columns(cur, spec)
                    files: list[dict[str, Any]] = []
                    total = 0
                    for sl in year_slices(first, last):
                        written = _dump_slice(cur, spec, sl, out_dir)
                        if written is None:
                            continue
                        total += written.rows
                        files.append(
                            {
                                "year": written.year,
                                "file": written.path.name,
                                "rows": written.rows,
                                "sha256": written.sha256,
                                "bytes_on_disk": written.bytes_on_disk,
                                "csv_bytes": written.csv_bytes,
                            }
                        )
                        print(
                            f"{spec.table} {sl.year}: {written.rows} rows, "
                            f"{written.bytes_on_disk} bytes gz",
                            flush=True,
                        )
                    manifest["tables"].append(
                        {
                            "table": spec.table,
                            "date_column": spec.date_column,
                            "columns": columns,
                            "total_rows": total,
                            "files": files,
                        }
                    )
    manifest["completed"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"manifest: {manifest_path} "
        f"({sum(t['total_rows'] for t in manifest['tables'])} rows, retention until "
        f"{RETENTION_UNTIL})",
        flush=True,
    )
    return 0


def _read_files(
    manifest: dict[str, Any], base: Path
) -> tuple[dict[tuple[str, int], int], dict[tuple[str, int], str]]:
    """Row counts and sha256 digests of every manifest file present on disk, keyed
    (table, year). A file the manifest names but the volume lacks stays absent from both
    dicts, so verification reports it missing instead of crashing on the open."""
    files: dict[tuple[str, int], int] = {}
    digests: dict[tuple[str, int], str] = {}
    for table in manifest["tables"]:
        name = table["table"]
        for entry in table["files"]:
            path = base / entry["file"]
            if not path.exists():
                continue
            key = (name, int(entry["year"]))
            files[key] = count_rows_in_file(path)
            digests[key] = sha256_of_file(path)
    return files, digests


def run_verify(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text())
    live: dict[tuple[str, int], int] = {}
    with _connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            with conn.cursor() as cur:
                for table in manifest["tables"]:
                    name = table["table"]
                    column = table["date_column"]
                    cur.execute(
                        f"SELECT extract(year from {column})::int AS y, count(*) "
                        f"FROM {name} GROUP BY 1 ORDER BY 1"
                    )
                    for year, count in cur.fetchall():
                        live[(name, year)] = count
    files, digests = _read_files(manifest, manifest_path.parent)
    problems = verify_slices(manifest, live, files, digests)
    totals = manifest_table_totals(manifest)
    report = {
        "manifest": str(manifest_path),
        "manifest_totals": totals,
        "live_totals": {name: sum(n for (t, _), n in live.items() if t == name) for name in totals},
        "file_totals": {
            name: sum(n for (t, _), n in files.items() if t == name) for name in totals
        },
        "problems": problems,
    }
    print(json.dumps(report, indent=2))
    if problems:
        print(f"VERIFY FAILED: {len(problems)} mismatch(es)", file=sys.stderr)
        return 1
    print("verify ok: manifest, live counts and files agree on every slice")
    return 0


def run_verify_files(manifest_path: Path) -> int:
    """The retention check once the tables are gone: manifest against files only."""
    manifest = json.loads(manifest_path.read_text())
    files, digests = _read_files(manifest, manifest_path.parent)
    problems = verify_files(manifest, files, digests)
    totals = manifest_table_totals(manifest)
    report = {
        "manifest": str(manifest_path),
        "manifest_totals": totals,
        "file_totals": {
            name: sum(n for (t, _), n in files.items() if t == name) for name in totals
        },
        "problems": problems,
    }
    print(json.dumps(report, indent=2))
    if problems:
        print(f"VERIFY FAILED: {len(problems)} mismatch(es)", file=sys.stderr)
        return 1
    print("verify ok: manifest and files agree on every slice (no database read)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dump", action="store_true", help="write the per-year gzip CSVs and manifest"
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="recount live and on disk against the manifest (needs the tables to exist)",
    )
    mode.add_argument(
        "--verify-files",
        action="store_true",
        help="recount the manifest's files only (rows and sha256, no database): the "
        "post-drop retention check",
    )
    parser.add_argument("--backup-dir", type=Path, default=_DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="default: <backup-dir>/old_store_backup_manifest.json",
    )
    args = parser.parse_args(argv)
    manifest = args.manifest or (args.backup_dir / _DEFAULT_MANIFEST)
    if args.dump:
        return run_dump(args.backup_dir, manifest)
    if args.verify_files:
        return run_verify_files(manifest)
    return run_verify(manifest)


if __name__ == "__main__":
    sys.exit(main())
