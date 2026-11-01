"""Generic backup-before-drop: COPY a table to per-year gzip CSV with verification.

The successor of scripts/ops/bars/ops_old_store_backup.py (todo 578): same machinery --
`--dump` writes, per table, one gzip CSV file per year slice of the table's date column into
the backup directory, streaming `COPY (SELECT * FROM <table> WHERE <slice>) TO STDOUT` through
one serial connection inside a single REPEATABLE READ transaction, plus a manifest JSON (table,
file, row count, sha256) beside the files; `--verify` recounts every year slice live inside one
REPEATABLE READ transaction and checks each file's rows and sha256 against the manifest;
`--verify-files` is the file half only (no database read), the retention-period check for a
backup sitting on disk. The script never removes anything and never writes to the database: its
only statements are SELECT, COPY ... TO STDOUT and catalog reads.

Tables are named on the command line (--table NAME --date-column COL [--bound-kind
timestamptz], repeatable), so any drop -- plain table or compressed hypertable -- can be
preceded by a sliced, verified backup. Plain small tables are often better served by
`pg_dump -Fc` (todo 571's own pattern); this tool exists for the hypertable-class drops where
pg_dump of a compressed chunk store is not the pattern, and for row-slice archives (--where
ANDs a literal predicate, e.g. the per-name archive of todo 512). A dump refuses to start when
free space on the backup volume is below the tables' total relation size times the APR key
`infra.table_backup.disk_margin` (default 2). CSV row counting assumes no value renders with an
embedded newline; a file that does not end in a newline is refused loudly rather than
miscounted.
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

_DEFAULT_BACKUP_DIR = project_root / "data" / "backups"
_DEFAULT_MANIFEST = "table_backup_manifest.json"


@dataclass(frozen=True)
class TableSpec:
    table: str
    date_column: str
    # "date" columns bound by an ISO date literal; "timestamptz" columns bound by an explicit
    # UTC instant, so no session timezone can move a slice boundary.
    bound_kind: str


DISK_MARGIN_KEY = "infra.table_backup.disk_margin"


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


def slice_select_sql(spec: TableSpec, lo: date, hi: date, where: str | None = None) -> str:
    sql = (
        f"SELECT * FROM {spec.table} WHERE {spec.date_column} >= "
        f"'{_bound(lo, spec.bound_kind)}' AND {spec.date_column} < '{_bound(hi, spec.bound_kind)}'"
    )
    return sql + f" AND ({where})" if where else sql


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
    cur: psycopg.Cursor,
    spec: TableSpec,
    sl: YearSlice,
    out_dir: Path,
    where: str | None = None,
) -> SliceFile | None:
    select_sql = slice_select_sql(spec, sl.lo, sl.hi, where)
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


def run_dump(
    specs: list[TableSpec],
    out_dir: Path,
    manifest_path: Path,
    retention_until: str,
    where: str | None,
) -> int:
    margin = asyncio.run(read_margin())
    out_dir.mkdir(parents=True, exist_ok=True)
    estimated = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for spec in specs:
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
        "retention_until": retention_until,
        "where": where,
        "disk_margin": margin,
        "estimated_bytes": estimated,
        "tables": [],
    }
    with _connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            with conn.cursor() as cur:
                for spec in specs:
                    first, last = _year_range(cur, spec)
                    columns = _columns(cur, spec)
                    files: list[dict[str, Any]] = []
                    total = 0
                    for sl in year_slices(first, last):
                        written = _dump_slice(cur, spec, sl, out_dir, where)
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
        f"{retention_until})",
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


def run_verify(manifest_path: Path, where: str | None = None) -> int:
    manifest = json.loads(manifest_path.read_text())
    live: dict[tuple[str, int], int] = {}
    with _connect() as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            with conn.cursor() as cur:
                for table in manifest["tables"]:
                    name = table["table"]
                    column = table["date_column"]
                    recount = f"SELECT extract(year from {column})::int AS y, count(*) FROM {name}"
                    if where:
                        recount += f" AND ({where})"
                    cur.execute(recount + " GROUP BY 1 ORDER BY 1")
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
        "--table",
        action="append",
        default=[],
        metavar="NAME[:DATE_COLUMN[:KIND]]",
        help="table to back up; repeat for several (required for --dump and --verify). "
        "DATE_COLUMN defaults to timestamp, KIND (date | timestamptz) to date",
    )
    parser.add_argument(
        "--where",
        default=None,
        help="extra ANDed predicate for every slice (e.g. a per-name archive); recorded in "
        "the manifest and applied again by --verify",
    )
    parser.add_argument(
        "--retention-until", default=None, help="recorded in the manifest beside the files"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="default: <backup-dir>/table_backup_manifest.json",
    )
    args = parser.parse_args(argv)
    manifest = args.manifest or (args.backup_dir / _DEFAULT_MANIFEST)
    specs = []
    for token in args.table:
        parts = token.split(":")
        name = parts[0]
        column = parts[1] or "timestamp" if len(parts) > 1 else "timestamp"
        kind = parts[2] or "date" if len(parts) > 2 else "date"
        if kind not in ("date", "timestamptz"):
            parser.error(f"{token}: KIND must be date or timestamptz, got {kind!r}")
        specs.append(TableSpec(name, column, kind))
    if args.dump or args.verify:
        if not specs:
            parser.error("at least one --table is required for --dump and --verify")
        if args.dump and args.retention_until is None:
            parser.error(
                "--retention-until is required for --dump (it is the record's own "
                "retention statement)"
            )
    if args.dump:
        return run_dump(specs, args.backup_dir, manifest, args.retention_until, args.where)
    if args.verify_files:
        return run_verify_files(manifest)
    return run_verify(manifest, args.where)


if __name__ == "__main__":
    sys.exit(main())
