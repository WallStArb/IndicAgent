"""Manifest-driven downloader for the Massive flat-file archive (todo 600).

Acquires both SIP aggregates at full depth (``us_stocks_sip/minute_aggs_v1`` and
``us_stocks_sip/day_aggs_v1``, 2003 to present, roughly 80-100 GB compressed) into
``data/massive/files/<dataset>/<YYYY>/<MM>/<name>.csv.gz``. Files land AS-DELIVERED:
bytes are never modified, every file is verified (size, sha256, gzip CRC, row count)
before it is renamed into place, and a per-file manifest record (``data/massive/manifest/
manifest.jsonl``) is the completeness proof that later replaces the ask-ledger gates.

Resume law: a key already in the manifest whose local size matches the listed size is
skipped; everything else (never-downloaded, interrupted, size-mismatched) re-downloads
into a ``.part`` file and is renamed atomically only after full verification. A kill at
any moment leaves at most one orphan ``.part`` and never a half-written archive file or
a manifest record for a file that is not on disk. Re-run the same command to resume.

Listing: the full key inventory (``data/massive/manifest/inventory.jsonl``) is listed
once via S3 ListObjectsV2 with continuation-token pagination and reused on later runs
unless ``--refresh-inventory`` is given.

Transport: curl with SigV4 (verified against ``files.massive.com``; no boto3 in the
venv). Credentials come from ``MASSIVE_S3_*`` in the environment or the repo ``.env``.
Downloaded files are untrusted input: nothing here executes inside the download tree.

Disk floor: a hard refusal (exit 2) before and during the run if free space would drop
below ``--min-free-gb`` (default 100). The archive is re-downloadable while the plan is
live, but the floor protects the database and the rest of the machine first.

Verification: ``--verify`` re-hashes every recorded file against its manifest record
(size plus sha256), the slow full check the resume law's size-only skip rests on. Run
it once after the archive completes; exit 1 names the defects.

Foreground/resumable batch: launched by the lead under nohup/tmux, kill-safe by the
manifest law above. No DB writes, no systemd wiring yet.

Usage:
    .venv/bin/python -m scripts.infrastructure.massive.massive_download \\
        [--data-root PATH] [--manifest-dir PATH]
        [--datasets minute_aggs_v1,day_aggs_v1]
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--inventory-only] [--refresh-inventory] [--verify]
        [--concurrency N] [--min-free-gb N]
"""

from __future__ import annotations

import argparse
import atexit
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import structlog
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.service_utils import format_iso_ts, setup_service_logging
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SIP_PREFIX = "us_stocks_sip"
DATASETS = ("minute_aggs_v1", "day_aggs_v1")
INVENTORY_NAME = "inventory.jsonl"
MANIFEST_NAME = "manifest.jsonl"
PART_SUFFIX = ".part"
KEY_NAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.csv\.gz")
DEFAULT_CONCURRENCY = 4
DEFAULT_MIN_FREE_GB = 100
RETRY_PASSES = 2
PROGRESS_EVERY_FILES = 50
JOB = "massive-download"

log = structlog.get_logger("massive_download")


class DiskFloorError(RuntimeError):
    """Free space would drop below the hard floor; the run refuses loudly."""


@dataclass(frozen=True)
class KeyEntry:
    """One object in the vendor bucket."""

    key: str
    dataset: str
    date: str
    size: int

    @property
    def filename(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    def local_path(self, files_root: Path) -> Path:
        """As-delivered layout: files/<dataset>/<YYYY>/<MM>/<name>."""
        year, month, _ = self.date.split("-")
        return files_root / self.dataset / year / month / self.filename


class S3Config(BaseSettings):
    """MASSIVE_S3_* credentials, read from the environment or an .env file.

    Environment variables win over the env file (pydantic-settings order).
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    access_key_id: str = Field(validation_alias="MASSIVE_S3_ACCESS_KEY_ID")
    secret_access_key: str = Field(validation_alias="MASSIVE_S3_SECRET_ACCESS_KEY")
    endpoint: str = Field(
        default="https://files.massive.com", validation_alias="MASSIVE_S3_ENDPOINT"
    )
    bucket: str = Field(default="flatfiles", validation_alias="MASSIVE_S3_BUCKET")

    @property
    def base_url(self) -> str:
        return f"{self.endpoint.rstrip('/')}/{self.bucket}"


def parse_key(key: str, size: int = 0) -> KeyEntry | None:
    """Parse ``us_stocks_sip/<dataset>/<YYYY>/<MM>/<YYYY-MM-DD>.csv.gz``."""
    parts = key.split("/")
    if len(parts) != 5 or parts[0] != SIP_PREFIX or parts[1] not in DATASETS:
        return None
    name = parts[4]
    if not KEY_NAME_RE.fullmatch(name):
        return None
    date = name.removesuffix(".csv.gz")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None
    if parts[2] != date[:4] or parts[3] != date[5:7]:
        return None  # path/date mismatch: two such keys would collide on one local file
    return KeyEntry(key=key, dataset=parts[1], date=date, size=size)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_list_xml(xml_text: str) -> tuple[list[tuple[str, int]], str | None]:
    """(key, size) pairs plus the next continuation token, from ListObjectsV2 XML."""
    entries: list[tuple[str, int]] = []
    token: str | None = None
    root = ET.fromstring(xml_text)
    for node in root.iter():
        tag = _local(node.tag)
        if tag == "Contents":
            key: str | None = None
            size = 0
            for child in node:
                child_tag = _local(child.tag)
                if child_tag == "Key":
                    key = child.text
                elif child_tag == "Size" and child.text:
                    size = int(child.text)
            if key is not None:
                entries.append((key, size))
        elif tag == "NextContinuationToken" and node.text:
            token = node.text
    return entries, token


def curl_run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, check=False)


_AUTH_CONFIG_PATH: Path | None = None


def auth_config_file(cfg: S3Config) -> Path:
    """A 0600 curl config file carrying the credentials, created once per process.

    The secret must never sit in argv: /proc/<pid>/cmdline is readable by any
    local process for the life of every curl, and a full run holds curls alive
    for hours.
    """
    global _AUTH_CONFIG_PATH
    if _AUTH_CONFIG_PATH is None:
        handle = tempfile.NamedTemporaryFile(
            "w", prefix="massive-curl-", suffix=".cfg", delete=False
        )
        handle.write(f'user = "{cfg.access_key_id}:{cfg.secret_access_key}"\n')
        handle.close()
        os.chmod(handle.name, 0o600)
        atexit.register(os.unlink, handle.name)
        _AUTH_CONFIG_PATH = Path(handle.name)
    return _AUTH_CONFIG_PATH


def curl_base_args(cfg: S3Config) -> list[str]:
    """The shared SigV4 transport prefix; call sites append URL and mode flags."""
    return [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--aws-sigv4",
        "aws:amz:us-east-1:s3",
        "-K",
        str(auth_config_file(cfg)),
    ]


def list_prefix(
    cfg: S3Config,
    dataset: str,
    page_size: int = 1000,
    runner: Callable[[list[str]], subprocess.CompletedProcess[bytes]] = curl_run,
) -> list[KeyEntry]:
    """Full paginated listing of one dataset prefix."""
    prefix = f"{SIP_PREFIX}/{dataset}/"
    entries: list[KeyEntry] = []
    token: str | None = None
    while True:
        url = f"{cfg.base_url}?list-type=2&prefix={quote(prefix, safe='')}&max-keys={page_size}"
        if token is not None:
            url += f"&continuation-token={quote(token, safe='')}"
        proc = runner(curl_base_args(cfg) + [url])
        if proc.returncode != 0:
            raise RuntimeError(
                f"S3 list failed for {prefix} (rc={proc.returncode}): "
                f"{proc.stderr.decode(errors='replace')[:500]}"
            )
        pairs, token = parse_list_xml(proc.stdout.decode(errors="replace"))
        for key, size in pairs:
            entry = parse_key(key, size=size)
            if entry is None:
                log.warning("inventory.unexpected_key", key=key)
                continue
            entries.append(entry)
        if token is None:
            return entries


def write_inventory(path: Path, entries: list[KeyEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for entry in entries:
            fh.write(
                json.dumps(
                    {
                        "key": entry.key,
                        "dataset": entry.dataset,
                        "date": entry.date,
                        "size": entry.size,
                    }
                )
                + "\n"
            )


def load_inventory(path: Path) -> list[KeyEntry]:
    entries: list[KeyEntry] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            entries.append(
                KeyEntry(key=row["key"], dataset=row["dataset"], date=row["date"], size=row["size"])
            )
    return entries


def ensure_inventory(
    inventory_path: Path,
    cfg: S3Config,
    datasets: list[str],
    refresh: bool,
    runner: Callable[[list[str]], subprocess.CompletedProcess[bytes]] = curl_run,
) -> list[KeyEntry]:
    if inventory_path.is_file() and not refresh:
        entries = load_inventory(inventory_path)
        log.info("inventory.loaded", path=str(inventory_path), keys=len(entries))
        return entries
    entries: list[KeyEntry] = []
    for dataset in datasets:
        listed = list_prefix(cfg, dataset, runner=runner)
        log.info("inventory.listed", dataset=dataset, keys=len(listed))
        entries.extend(listed)
    entries.sort(key=lambda entry: (entry.dataset, entry.key))
    write_inventory(inventory_path, entries)
    log.info("inventory.written", path=str(inventory_path), keys=len(entries))
    return entries


def load_manifest(path: Path) -> dict[str, dict]:
    """Latest record per key (the manifest is append-only across resumes).

    A malformed final line (the one artifact a kill mid-append can leave) is
    warned and ignored so a rerun still resumes; damage anywhere else raises.
    """
    index: dict[str, dict] = {}
    if not path.is_file():
        return index
    lines = [line for line in (raw.strip() for raw in path.read_text().splitlines()) if line]
    for position, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if position == len(lines) - 1:
                log.warning("manifest.torn_trailing_line_skipped", line=line[:100])
                continue
            raise
        index[record["key"]] = record
    return index


def append_manifest(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def plan_downloads(
    entries: list[KeyEntry],
    manifest_index: dict[str, dict],
    files_root: Path,
) -> tuple[list[KeyEntry], int]:
    """(entries to download, count skipped). A manifest record whose local size
    matches the listed size is done; anything else re-downloads."""
    todo: list[KeyEntry] = []
    skipped = 0
    for entry in entries:
        record = manifest_index.get(entry.key)
        if record is not None:
            local = entry.local_path(files_root)
            if local.is_file() and local.stat().st_size == entry.size:
                skipped += 1
                continue
        todo.append(entry)
    return todo, skipped


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def floor_breached(free: int, incoming: int, floor: int) -> bool:
    """The one disk-floor law: refuse when free space minus incoming dips below floor."""
    return free - incoming < floor


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_rows(path: Path) -> int:
    """Data rows via a full decompress (validates the CRC); raises on corruption.

    Rows exclude the ``ticker,...`` header line; a trailing partial line still
    counts. The vendor format is fixed (header present, measured step 0), so a
    headerless file would shift the informational count by one without failing.
    """
    with gzip.open(path, "rb") as fh:
        first = fh.readline()
        if not first:
            return 0
        newlines = 0
        trailing = False
        while chunk := fh.read(1 << 20):
            newlines += chunk.count(b"\n")
            trailing = not chunk.endswith(b"\n")
    return newlines + (1 if trailing else 0)


def curl_fetch(cfg: S3Config, entry: KeyEntry, dest: Path) -> None:
    url = f"{cfg.base_url}/{entry.key}"
    proc = curl_run(
        curl_base_args(cfg)
        + [
            "--retry",
            "5",
            "--retry-delay",
            "5",
            "--retry-all-errors",
            url,
            "--output",
            str(dest),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"download failed rc={proc.returncode}: "
            f"{proc.stderr.decode(errors='replace')[:300]}"
        )


def download_one(
    entry: KeyEntry,
    files_root: Path,
    cfg: S3Config,
    min_free_bytes: int,
    fetch_fn: Callable[[S3Config, KeyEntry, Path], None] = curl_fetch,
    disk_free_fn: Callable[[Path], int] = free_bytes,
) -> dict:
    """Fetch, verify and move one file into place; return its manifest record.

    Raises DiskFloorError before fetching if the floor would be breached and
    RuntimeError on any transfer or verification failure (the .part file is removed;
    no manifest record is written; the caller's retry pass picks it up).
    """
    dest = entry.local_path(files_root)
    part = dest.with_name(dest.name + PART_SUFFIX)
    if floor_breached(disk_free_fn(files_root), entry.size, min_free_bytes):
        raise DiskFloorError(
            f"free space at or below the hard floor "
            f"({min_free_bytes} bytes); refusing before {entry.key}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        fetch_fn(cfg, entry, part)
        actual = part.stat().st_size
        if actual != entry.size:
            raise RuntimeError(f"size mismatch for {entry.key}: listed {entry.size}, got {actual}")
        rows = gzip_rows(part)
        digest = sha256_file(part)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    # gzip_ok is constant True by construction: a record only exists after the
    # full-decompress CRC check in gzip_rows passed. Kept so the record states
    # every completeness fact the file manifest promises.
    return {
        "dataset": entry.dataset,
        "key": entry.key,
        "path": str(dest.relative_to(files_root)),
        "bytes": entry.size,
        "sha256": digest,
        "rows": rows,
        "gzip_ok": True,
        "downloaded_at": format_iso_ts(datetime.now(UTC)),
    }


def verify_archive(manifest_path: Path, files_root: Path) -> int:
    """Re-hash every recorded file against its manifest record (bit-rot check).

    The resume law is size-only for speed; this is the slow full check the
    completeness proof ultimately rests on. Returns the defect count."""
    index = load_manifest(manifest_path)
    defects = 0
    for record in index.values():
        local = files_root / record["path"]
        if not local.is_file():
            log.error("verify.missing", key=record["key"])
            defects += 1
            continue
        if local.stat().st_size != record["bytes"] or sha256_file(local) != record["sha256"]:
            log.error("verify.mismatch", key=record["key"], path=record["path"])
            defects += 1
    log.info("verify.done", records=len(index), defects=defects)
    print(f"verify: {len(index)} records, {defects} defects")
    return defects


def filter_entries(
    entries: list[KeyEntry],
    datasets: set[str],
    date_from: str | None,
    date_to: str | None,
) -> list[KeyEntry]:
    return [
        entry
        for entry in entries
        if entry.dataset in datasets
        and (date_from is None or entry.date >= date_from)
        and (date_to is None or entry.date <= date_to)
    ]


def human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def run(
    args: argparse.Namespace,
    cfg: S3Config | None = None,
    list_runner: Callable[[list[str]], subprocess.CompletedProcess[bytes]] = curl_run,
    fetch_fn: Callable[[S3Config, KeyEntry, Path], None] = curl_fetch,
) -> int:
    setup_service_logging(str(REPO_ROOT / "logs" / "massive_download.log"))
    if cfg is None:
        try:
            cfg = S3Config(_env_file=args.env_file)
        except ValidationError as error:
            raise SystemExit(
                f"missing MASSIVE_S3 credentials in environment or {args.env_file}: {error}"
            ) from error

    files_root = args.data_root / "files"
    manifest_dir = args.manifest_dir
    inventory_path = manifest_dir / INVENTORY_NAME
    manifest_path = manifest_dir / MANIFEST_NAME

    if args.verify:
        defects = verify_archive(manifest_path, files_root)
        return 1 if defects else 0

    entries = ensure_inventory(
        inventory_path, cfg, args.datasets, args.refresh_inventory, runner=list_runner
    )
    selected = filter_entries(entries, set(args.datasets), args.date_from, args.date_to)
    total_bytes = sum(entry.size for entry in selected)
    log.info(
        "plan.selected",
        files=len(selected),
        bytes=total_bytes,
        human=human_bytes(total_bytes),
    )

    if args.inventory_only:
        inventory_bytes = sum(entry.size for entry in entries)
        print(
            f"inventory: {len(entries)} keys, {human_bytes(inventory_bytes)}; "
            f"selected {len(selected)} keys, {human_bytes(total_bytes)}; "
            f"written to {inventory_path}"
        )
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": "success"})
        flush_and_shutdown_metrics()
        return 0

    manifest_index = load_manifest(manifest_path)
    todo, skipped = plan_downloads(selected, manifest_index, files_root)
    todo_bytes = sum(entry.size for entry in todo)
    log.info(
        "plan.resolved",
        todo=len(todo),
        todo_bytes=human_bytes(todo_bytes),
        skipped=skipped,
    )
    print(
        f"plan: {len(todo)} files to download ({human_bytes(todo_bytes)}), "
        f"{skipped} already done"
    )

    if not todo:
        print("nothing to do")
        return 0

    min_free_bytes = args.min_free_gb * (1 << 30)
    files_root.mkdir(parents=True, exist_ok=True)
    free = free_bytes(files_root)
    if floor_breached(free, todo_bytes, min_free_bytes):
        log.error(
            "disk.floor_preflight_refusal",
            free_bytes=free,
            plan_bytes=todo_bytes,
            min_free_bytes=min_free_bytes,
        )
        print(
            f"REFUSING: free {human_bytes(free)} minus plan {human_bytes(todo_bytes)} "
            f"would breach the {args.min_free_gb} GB floor",
            file=sys.stderr,
        )
        return 2

    done_bytes = 0
    done_files = 0
    started = time.monotonic()
    interrupted = False
    floor_stopped = False

    def execute(batch: list[KeyEntry]) -> list[KeyEntry]:
        nonlocal done_bytes, done_files, interrupted, floor_stopped
        failed: list[KeyEntry] = []
        stopped = False
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(
                    download_one, entry, files_root, cfg, min_free_bytes, fetch_fn
                ): entry
                for entry in batch
            }
            try:
                for future in as_completed(futures):
                    entry = futures[future]
                    try:
                        record = future.result()
                    except DiskFloorError as error:
                        log.error("disk.floor_refusal", key=entry.key, error=str(error))
                        floor_stopped = True
                        stopped = True
                        break
                    except KeyboardInterrupt:
                        interrupted = True
                        stopped = True
                        break
                    except Exception as error:  # noqa: BLE001 -- per-file failure is retryable
                        log.warning("download.failed", key=entry.key, error=str(error))
                        failed.append(entry)
                        continue
                    append_manifest(manifest_path, record)
                    done_bytes += record["bytes"]
                    done_files += 1
                    log.info(
                        "download.ok",
                        key=entry.key,
                        bytes=record["bytes"],
                        rows=record["rows"],
                    )
                    if done_files % PROGRESS_EVERY_FILES == 0:
                        elapsed = time.monotonic() - started
                        rate = done_bytes / elapsed if elapsed else 0.0
                        log.info(
                            "progress",
                            done_files=done_files,
                            done_bytes=human_bytes(done_bytes),
                            rate=human_bytes(int(rate)) + "/s",
                        )
            finally:
                if stopped:
                    executor.shutdown(cancel_futures=True)
        return failed

    failures = execute(todo)
    for attempt in range(1, 1 + RETRY_PASSES):
        if not failures or interrupted or floor_stopped:
            break
        log.info("retry.pass", attempt=attempt, files=len(failures))
        failures = execute(failures)

    elapsed = time.monotonic() - started
    status = "failure" if (failures or interrupted or floor_stopped) else "success"
    JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
    flush_and_shutdown_metrics()
    if floor_stopped:
        log.error("disk.floor_stopped_run")
        print(
            f"REFUSING mid-run: free space reached the {args.min_free_gb} GB floor; "
            f"rerun when space is freed",
            file=sys.stderr,
        )
        return 2
    if interrupted:
        log.error("run.interrupted")
        print("INTERRUPTED: rerun the same command to resume", file=sys.stderr)
        return 130
    if failures:
        log.error("run.incomplete", remaining=len(failures))
        print(
            f"FAILED after retries: {len(failures)} files; rerun to retry",
            file=sys.stderr,
        )
        return 1
    rate = done_bytes / elapsed if elapsed else 0.0
    log.info(
        "run.done",
        files=len(todo),
        bytes=done_bytes,
        elapsed_s=round(elapsed, 1),
        rate=human_bytes(int(rate)) + "/s",
    )
    print(
        f"done: {len(todo)} files, {human_bytes(done_bytes)}, "
        f"{elapsed:.0f}s, {human_bytes(int(rate))}/s"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-root",
        type=Path,
        default=REPO_ROOT / "data" / "massive",
        help="archive root (files land in <data-root>/files/...)",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=REPO_ROOT / "data" / "massive" / "manifest",
    )
    parser.add_argument(
        "--datasets",
        default=",".join(DATASETS),
        help="comma-separated dataset names under us_stocks_sip/",
    )
    parser.add_argument("--date-from", default=None, help="inclusive YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="inclusive YYYY-MM-DD")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--refresh-inventory", action="store_true")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-hash every manifest-recorded file (size + sha256) and exit",
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--min-free-gb", type=int, default=DEFAULT_MIN_FREE_GB)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.datasets = [name.strip() for name in args.datasets.split(",") if name.strip()]
    for name in args.datasets:
        if name not in DATASETS:
            print(f"unknown dataset: {name}", file=sys.stderr)
            return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
