"""Manifest-driven downloader for the Massive flat-file archive (todo 600).

Acquires both SIP aggregates at full depth (``us_stocks_sip/minute_aggs_v1`` and
``us_stocks_sip/day_aggs_v1``, 2003 to present, roughly 80-100 GB compressed) into
``data/massive/files/<dataset>/<YYYY>/<MM>/<name>.csv.gz``. Files land AS-DELIVERED:
bytes are never modified, every file is verified (size, sha256, gzip CRC, row count)
before it is renamed into place, and a per-file manifest record (``data/massive/manifest/
manifest.jsonl``) is the completeness proof that later replaces the ask-ledger gates.

Resume law: a key already in the manifest is skipped only if its local size matches the
listed size AND the recorded ETag equals the listed ETag; everything else
(never-downloaded, interrupted, size-mismatched, ETag-changed) re-downloads into a
``.part`` file and is renamed atomically only after full verification. A kill at any
moment leaves at most one orphan ``.part`` and never a half-written archive file or a
manifest record for a file that is not on disk. Re-run the same command to resume.

Supersession: when the vendor restates a key (the ETag changed), the old bytes are moved
to ``<data-root>/superseded/<dataset>/<YYYY>/<MM>/<name>.superseded-<etag8>`` (outside
``files/``, never read by a loader) and the new manifest record carries a ``supersedes``
block (old etag, sha256, bytes, path, last_modified). Bytes are never overwritten in
place. The old bytes are moved only after their sha256 is proven equal to the previous
record's; an absent or different destination refuses loudly (``SupersessionRefusedError``,
exit 2, never retried). A same-ETag re-download (a damaged or missing local copy) and a
new ETag over identical bytes (same sha256) are repairs, not supersessions; the same ETag
over different bytes is logged as an error.

Serve labels come from the download response, never from the cached inventory: curl
writes the response ``ETag`` and ``Last-Modified`` headers to stdout (``--write-out``),
the file fails when the response ETag differs from the inventory ETag, and a single-part
ETag (32 hex, no dash) must equal the md5 of the bytes received. Empty ETag or
Last-Modified refuses everywhere.

Serve fields: the inventory and every manifest record carry the vendor ``etag`` (bare
hex, quotes stripped) and ``last_modified`` per key. Records written before this law lack
them: ``--migrate-manifest`` (one-shot, already run on the live manifest) joins them from
``servetimes_*.jsonl`` (``join_servetimes``, migration code only: after migration the
loader reads the manifest alone) and appends enriched records; an inventory without ETags
needs ``--refresh-inventory``. A run that meets a missing ETag refuses loudly rather than
guess.

Locking and appends: any mode that writes (download, migrate, refresh) holds an exclusive
``flock`` on ``<manifest-dir>/.lock``; a second writer refuses (exit 2). The manifest is
append-only with fsync per record; a torn final line from a kill is dropped on the next
append and ignored on load.

Listing: the full key inventory (``data/massive/manifest/inventory.jsonl``) is listed
once via S3 ListObjectsV2 with continuation-token pagination and reused on later runs
unless ``--refresh-inventory`` is given (written atomically; a ``--datasets`` subset is
merged into the existing inventory, and refused when that would leave a dataset out).
Without ``--inventory-only`` a refresh also goes on to download. A listing that ends
truncated without a token, or holds a key the parser rejects, fails the listing.

Transport: curl with SigV4 (verified against ``files.massive.com``; no boto3 in the
venv). Credentials come from ``MASSIVE_S3_*`` in the environment or the repo ``.env``.
Downloaded files are untrusted input: nothing here executes inside the download tree.

Disk floor: a hard refusal (exit 2) before and during the run if free space would drop
below ``--min-free-gb`` (default 100). The archive is re-downloadable while the plan is
live, but the floor protects the database and the rest of the machine first.

Verification: ``--verify`` re-hashes every recorded file against its manifest record
(size plus sha256), the slow full check the resume law's size-only skip rests on, and
every archived file under ``superseded/``. Run it once after the archive completes; exit
1 names the defects. ``--verify-etag`` streams every archived file once (parallel) and
compares md5 to each single-part ETag; with ``--migrate-manifest`` it gates the join on
the same md5 check.

Exit codes: 0 ok, 1 failure or drift or defects, 2 refusal (disk floor, missing serve
fields, supersession proof, held lock, inventory scope).

Restat: ``--restat`` (no downloads) re-lists the vendor prefixes, compares ETag and size
to the manifest, writes a drift report JSON (``--drift-report``, default
``<manifest-dir>/etag_drift_<date>.json``; an empty list when clean) and exits 1 on any
drift. Keys the vendor no longer lists count as drift; keys new to the vendor do not.

Foreground/resumable batch: launched by the lead under nohup/tmux, kill-safe by the
manifest law above. No DB writes, no systemd wiring yet.

Usage:
    .venv/bin/python -m scripts.infrastructure.massive.massive_download \\
        [--data-root PATH] [--manifest-dir PATH]
        [--datasets minute_aggs_v1,day_aggs_v1]
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--inventory-only] [--refresh-inventory] [--verify]
        [--restat [--drift-report PATH]] [--migrate-manifest] [--verify-etag]
        [--concurrency N] [--min-free-gb N]
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import structlog
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.service_utils import format_iso_ts, parse_iso_ts, setup_service_logging
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SIP_PREFIX = "us_stocks_sip"
DATASETS = ("minute_aggs_v1", "day_aggs_v1")
INVENTORY_NAME = "inventory.jsonl"
SERVETIMES_GLOB = "servetimes_*.jsonl"
SUPERSEDED_DIR = "superseded"
MANIFEST_NAME = "manifest.jsonl"
LOCK_NAME = ".lock"
EXIT_FAILED = 1
EXIT_REFUSED = 2
SINGLE_PART_ETAG_RE = re.compile(r"[0-9a-f]{32}")
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


class MissingServeFieldsError(RuntimeError):
    """An inventory entry or manifest record lacks its ETag; migrate or refresh first."""


class ManifestJoinError(RuntimeError):
    """The manifest-to-servetimes join failed one of its proofs (key, ETag, size, time, md5)."""


class SupersessionRefusedError(RuntimeError):
    """The old bytes cannot be proven (absent or a different sha256); stops the run, never
    retried."""


class InventoryScopeError(RuntimeError):
    """A refresh would write an inventory that leaves a dataset out."""


class ManifestLockedError(RuntimeError):
    """Another writer holds the manifest directory lock."""


class ServeLabelError(RuntimeError):
    """A download response lacks an ETag or Last-Modified, or its ETag or md5 disagrees
    with the inventory; the file fails (retryable after a refresh)."""


@dataclass(frozen=True)
class Served:
    """The vendor labels read from one download response."""

    etag: str
    last_modified: str


FetchFn = Callable[["S3Config", "KeyEntry", Path], Served]
CurlRunner = Callable[[list[str], bytes | None], subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class KeyEntry:
    """One object in the vendor bucket."""

    key: str
    dataset: str
    date: str
    size: int
    etag: str = ""
    last_modified: str = ""

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

    access_key_id: SecretStr = Field(validation_alias="MASSIVE_S3_ACCESS_KEY_ID")
    secret_access_key: SecretStr = Field(validation_alias="MASSIVE_S3_SECRET_ACCESS_KEY")
    endpoint: str = Field(
        default="https://files.massive.com", validation_alias="MASSIVE_S3_ENDPOINT"
    )
    bucket: str = Field(default="flatfiles", validation_alias="MASSIVE_S3_BUCKET")

    @property
    def base_url(self) -> str:
        return f"{self.endpoint.rstrip('/')}/{self.bucket}"


def normalize_etag(raw: str) -> str:
    """Bare hex: the S3 ETag arrives quoted, and the captured servetimes files carry the
    quotes HTML-escaped; every comparison goes through this one form. A weak validator
    (``W/``) is not a content hash and is rejected."""
    value = html.unescape(raw).strip()
    if value.startswith(("W/", "w/")):
        raise ValueError(f"weak ETag is not a content hash: {raw!r}")
    return value.strip('"')


def is_single_part_etag(etag: str) -> bool:
    """A 32-hex ETag with no dash is the md5 of the object; multipart ETags carry a dash."""
    return SINGLE_PART_ETAG_RE.fullmatch(etag) is not None


def parse_key(key: str, size: int = 0, etag: str = "", last_modified: str = "") -> KeyEntry | None:
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
    return KeyEntry(
        key=key,
        dataset=parts[1],
        date=date,
        size=size,
        etag=normalize_etag(etag),
        last_modified=last_modified,
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_list_xml(xml_text: str) -> tuple[list[tuple[str, int, str, str]], str | None, bool]:
    """(key, size, etag, last_modified) rows, the next continuation token and the
    IsTruncated flag, from ListObjectsV2 XML."""
    entries: list[tuple[str, int, str, str]] = []
    token: str | None = None
    truncated = False
    root = ET.fromstring(xml_text)
    for node in root.iter():
        tag = _local(node.tag)
        if tag == "Contents":
            key: str | None = None
            size = 0
            etag = last_modified = ""
            for child in node:
                child_tag = _local(child.tag)
                if child_tag == "Key":
                    key = child.text
                elif child_tag == "Size" and child.text:
                    size = int(child.text)
                elif child_tag == "ETag" and child.text:
                    etag = child.text
                elif child_tag == "LastModified" and child.text:
                    last_modified = child.text
            if key is not None:
                entries.append((key, size, etag, last_modified))
        elif tag == "NextContinuationToken" and node.text:
            token = node.text
        elif tag == "IsTruncated" and node.text:
            truncated = node.text.strip().lower() == "true"
    return entries, token, truncated


def curl_run(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run curl; the credentials, when the args ask for ``-K -``, go in on ``stdin``."""
    return subprocess.run(args, capture_output=True, check=False, input=stdin)


def _config_quote(value: str) -> str:
    """Escape a value for a curl config double-quoted string."""
    if "\n" in value or "\r" in value:
        raise ValueError("credential contains a line break")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def curl_auth_stdin(cfg: S3Config) -> bytes:
    """The ``-K -`` config the secret travels in; held in memory, never on disk or argv."""
    pair = f"{cfg.access_key_id.get_secret_value()}:{cfg.secret_access_key.get_secret_value()}"
    return f'user = "{_config_quote(pair)}"\n'.encode()


def curl_base_args(cfg: S3Config) -> list[str]:
    """The shared SigV4 transport prefix; call sites append URL and mode flags and pass
    ``curl_auth_stdin(cfg)`` as the process stdin.

    The secret never sits in argv (/proc/<pid>/cmdline is readable by any local process
    for the life of every curl) and never in a file: a temp config is deleted by a /tmp
    cleanup mid-run (every transfer then fails) and leaks when a kill skips atexit. It is
    handed to each curl on stdin through ``-K -``.
    """
    return [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--aws-sigv4",
        "aws:amz:us-east-1:s3",
        "-K",
        "-",
    ]


def list_prefix(
    cfg: S3Config,
    dataset: str,
    page_size: int = 1000,
    runner: CurlRunner = curl_run,
) -> list[KeyEntry]:
    """Full paginated listing of one dataset prefix. Fails on a truncated page without a
    continuation token and on any key the parser rejects (or outside the prefix)."""
    prefix = f"{SIP_PREFIX}/{dataset}/"
    entries: list[KeyEntry] = []
    rejected: list[str] = []
    token: str | None = None
    while True:
        url = f"{cfg.base_url}?list-type=2&prefix={quote(prefix, safe='')}&max-keys={page_size}"
        if token is not None:
            url += f"&continuation-token={quote(token, safe='')}"
        proc = runner(curl_base_args(cfg) + [url], curl_auth_stdin(cfg))
        if proc.returncode != 0:
            raise RuntimeError(
                f"S3 list failed for {prefix} (rc={proc.returncode}): "
                f"{proc.stderr.decode(errors='replace')[:500]}"
            )
        pairs, token, truncated = parse_list_xml(proc.stdout.decode(errors="replace"))
        if truncated and token is None:
            raise RuntimeError(f"S3 list for {prefix} is truncated without a continuation token")
        for key, size, etag, last_modified in pairs:
            entry = parse_key(key, size=size, etag=etag, last_modified=last_modified)
            if entry is None or entry.dataset != dataset:
                rejected.append(key)
                continue
            entries.append(entry)
        if token is None:
            break
    if rejected:
        raise RuntimeError(
            f"S3 list for {prefix} holds {len(rejected)} keys the parser rejects, "
            f"first {rejected[:3]}"
        )
    return entries


def write_inventory(path: Path, entries: list[KeyEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        for entry in entries:
            fh.write(
                json.dumps(
                    {
                        "key": entry.key,
                        "dataset": entry.dataset,
                        "date": entry.date,
                        "size": entry.size,
                        "etag": entry.etag,
                        "last_modified": entry.last_modified,
                    }
                )
                + "\n"
            )
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_inventory(path: Path) -> list[KeyEntry]:
    entries: list[KeyEntry] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            entries.append(
                KeyEntry(
                    key=row["key"],
                    dataset=row["dataset"],
                    date=row["date"],
                    size=row["size"],
                    etag=row.get("etag", ""),
                    last_modified=row.get("last_modified", ""),
                )
            )
    return entries


def ensure_inventory(
    inventory_path: Path,
    cfg: S3Config,
    datasets: list[str],
    refresh: bool,
    runner: CurlRunner = curl_run,
) -> list[KeyEntry]:
    """Load the inventory, or list ``datasets`` and write it atomically. A listing of a
    subset keeps the other datasets from the existing inventory; if that still leaves a
    dataset out the write is refused (a later plain run would silently skip it)."""
    existing: list[KeyEntry] = []
    if inventory_path.is_file():
        existing = load_inventory(inventory_path)
        if not refresh:
            log.info("inventory.loaded", path=str(inventory_path), keys=len(existing))
            return existing
    entries = [entry for entry in existing if entry.dataset not in datasets]
    if {entry.dataset for entry in entries} | set(datasets) != set(DATASETS):
        raise InventoryScopeError(
            f"listing {datasets} would leave the inventory without the other datasets; "
            f"list all of {list(DATASETS)} or merge into an existing inventory"
        )
    for dataset in datasets:
        listed = list_prefix(cfg, dataset, runner=runner)
        log.info("inventory.listed", dataset=dataset, keys=len(listed))
        entries.extend(listed)
    entries.sort(key=lambda entry: (entry.dataset, entry.key))
    write_inventory(inventory_path, entries)
    log.info("inventory.written", path=str(inventory_path), keys=len(entries))
    return entries


def load_manifest_history(path: Path) -> list[dict]:
    """Every record in file order (the manifest is append-only across resumes).

    A malformed final line (the one artifact a kill mid-append can leave) is
    warned and ignored so a rerun still resumes; damage anywhere else raises.
    """
    records: list[dict] = []
    if not path.is_file():
        return records
    lines = [line for line in (raw.strip() for raw in path.read_text().splitlines()) if line]
    for position, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if position == len(lines) - 1:
                log.warning("manifest.torn_trailing_line_skipped", line=line[:100])
                continue
            raise
    return records


def load_manifest(path: Path) -> dict[str, dict]:
    """Latest record per key."""
    return {record["key"]: record for record in load_manifest_history(path)}


TAIL_WINDOW_BYTES = 1 << 16


def _heal_tail(fh) -> None:  # noqa: ANN001
    """Leave the append handle at the end of a complete line. A kill mid-append leaves a
    final line without its newline: valid JSON gets the newline, a torn fragment is
    truncated away (appending after it would bury a malformed line mid-file)."""
    size = fh.seek(0, os.SEEK_END)
    if size == 0:
        return
    start = max(0, size - TAIL_WINDOW_BYTES)
    fh.seek(start)
    tail = fh.read()
    if tail.endswith(b"\n"):
        return
    cut = tail.rfind(b"\n") + 1
    fragment = tail[cut:]
    try:
        json.loads(fragment)
    except json.JSONDecodeError:
        log.warning(
            "manifest.torn_tail_truncated", fragment=fragment[:100].decode(errors="replace")
        )
        fh.truncate(start + cut)
        fh.seek(0, os.SEEK_END)
    else:
        fh.write(b"\n")


def append_manifest(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab+") as fh:
        _heal_tail(fh)
        fh.write((json.dumps(record) + "\n").encode())
        fh.flush()
        os.fsync(fh.fileno())


def plan_downloads(
    entries: list[KeyEntry],
    manifest_index: dict[str, dict],
    files_root: Path,
) -> tuple[list[KeyEntry], int]:
    """(entries to download, count skipped).

    A key is skipped only if a manifest record exists, the local size equals the listed
    size AND the recorded ETag equals the listed ETag. An ETag change with equal size
    re-downloads (a restatement). A missing ETag on either side raises: guessing would
    either skip a restated file or re-download the whole archive.
    """
    todo: list[KeyEntry] = []
    skipped = 0
    for entry in entries:
        if not entry.etag:
            raise MissingServeFieldsError(
                f"inventory entry {entry.key} has no ETag; rerun with --refresh-inventory"
            )
        record = manifest_index.get(entry.key)
        if record is not None:
            if not record.get("etag"):
                raise MissingServeFieldsError(
                    f"manifest record {entry.key} has no ETag; run --migrate-manifest"
                )
            local = entry.local_path(files_root)
            if record["etag"] != entry.etag:
                log.warning(
                    "plan.etag_changed",
                    key=entry.key,
                    recorded=record["etag"],
                    listed=entry.etag,
                )
            elif local.is_file() and local.stat().st_size == entry.size:
                skipped += 1
                continue
        todo.append(entry)
    return todo, skipped


def load_servetimes(manifest_dir: Path) -> dict[str, dict]:
    """key -> {etag, last_modified, size} from ``servetimes_*.jsonl`` (tab-separated:
    key, LastModified, ETag, size). A key in two files raises."""
    serve: dict[str, dict] = {}
    for path in sorted(manifest_dir.glob(SERVETIMES_GLOB)):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            key, last_modified, etag, size = line.split("\t")
            if key in serve:
                raise ManifestJoinError(f"servetimes key listed twice: {key}")
            serve[key] = {
                "etag": normalize_etag(etag),
                "last_modified": last_modified,
                "size": int(size),
            }
    return serve


def _required_ts(key: str, value: str | None) -> datetime:
    parsed = parse_iso_ts(value)
    if parsed is None:
        raise ManifestJoinError(f"{key}: unparseable timestamp {value!r}")
    return parsed


def join_servetimes(
    records: Iterable[dict],
    servetimes: dict[str, dict],
    md5_of: Callable[[dict], str] | None = None,
) -> list[dict]:
    """ONE-SHOT MIGRATION CODE (already run on the live manifest): records lacking an
    ETag, enriched with ``etag`` and ``last_modified`` from the servetimes capture
    (records that already carry an ETag pass through untouched and are not returned).
    After migration the loader reads the manifest only; nothing reuses this.

    Raises ManifestJoinError on the first key absent from servetimes, with an empty ETag
    or Last-Modified there, whose recorded size differs from the captured size, whose
    captured Last-Modified is later than the record's ``downloaded_at`` (the label would
    then describe a newer upload than the bytes on disk), or, when ``md5_of`` is given
    (opt-in, streams the file), whose single-part ETag differs from the md5 of the file.
    """
    enriched: list[dict] = []
    for record in records:
        if record.get("etag"):
            continue
        key = record["key"]
        served = servetimes.get(key)
        if served is None:
            raise ManifestJoinError(f"{key}: not in servetimes")
        if not served["etag"]:
            raise ManifestJoinError(f"{key}: servetimes ETag is empty")
        if not served["last_modified"]:
            raise ManifestJoinError(f"{key}: servetimes LastModified is empty")
        if served["size"] != record["bytes"]:
            raise ManifestJoinError(
                f"{key}: manifest bytes {record['bytes']} != servetimes size {served['size']}"
            )
        if _required_ts(key, served["last_modified"]) > _required_ts(
            key, record.get("downloaded_at")
        ):
            raise ManifestJoinError(
                f"{key}: servetimes LastModified {served['last_modified']} is later than "
                f"downloaded_at {record['downloaded_at']}"
            )
        if md5_of is not None and is_single_part_etag(served["etag"]):
            if md5_of(record) != served["etag"]:
                raise ManifestJoinError(f"{key}: md5 of the file differs from servetimes ETag")
        enriched.append(
            {
                **record,
                "etag": served["etag"],
                "last_modified": served["last_modified"],
                "serve_fields_source": "servetimes",
            }
        )
    return enriched


def migrate_manifest(
    manifest_path: Path,
    manifest_dir: Path,
    md5_of: Callable[[dict], str] | None = None,
) -> int:
    """Append an enriched record per ETag-less manifest record (append-only; the
    originals stay). Idempotent: a rerun finds nothing left to migrate."""
    enriched = join_servetimes(
        load_manifest(manifest_path).values(), load_servetimes(manifest_dir), md5_of
    )
    for record in enriched:
        append_manifest(manifest_path, record)
    log.info("manifest.migrated", records=len(enriched))
    print(f"migrate: {len(enriched)} records enriched with etag and last_modified")
    return len(enriched)


def restat_drift(manifest_index: dict[str, dict], listed: list[KeyEntry]) -> list[dict]:
    """Drift rows between the manifest and a fresh listing: a changed ETag or size, or a
    recorded key the vendor no longer lists. Keys new to the vendor are not drift."""
    listed_by_key = {entry.key: entry for entry in listed}
    drift: list[dict] = []
    for key, record in sorted(manifest_index.items()):
        if not record.get("etag"):
            raise MissingServeFieldsError(
                f"manifest record {key} has no ETag; run --migrate-manifest"
            )
        entry = listed_by_key.get(key)
        recorded = {
            "etag": record["etag"],
            "size": record["bytes"],
            "last_modified": record.get("last_modified", ""),
        }
        if entry is None:
            drift.append({"key": key, "changed": ["missing"], "manifest": recorded, "listed": None})
            continue
        changed = [
            name
            for name, differs in (
                ("etag", entry.etag != record["etag"]),
                ("size", entry.size != record["bytes"]),
            )
            if differs
        ]
        if changed:
            drift.append(
                {
                    "key": key,
                    "changed": changed,
                    "manifest": recorded,
                    "listed": {
                        "etag": entry.etag,
                        "size": entry.size,
                        "last_modified": entry.last_modified,
                    },
                }
            )
    return drift


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def floor_breached(free: int, incoming: int, floor: int) -> bool:
    """The one disk-floor law: refuse when free space minus incoming dips below floor."""
    return free - incoming < floor


def file_digests(path: Path, algorithms: tuple[str, ...] = ("sha256",)) -> dict[str, str]:
    """Hex digests of one file, every algorithm in a single streaming pass."""
    hashers = {name: hashlib.new(name) for name in algorithms}
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            for hasher in hashers.values():
                hasher.update(chunk)
    return {name: hasher.hexdigest() for name, hasher in hashers.items()}


def sha256_file(path: Path) -> str:
    return file_digests(path)["sha256"]


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


WRITE_OUT = "%header{etag}\\n%header{last-modified}\\n"


def parse_write_out(stdout: bytes) -> Served:
    """The last two lines of curl's write-out (``--retry`` can print one block per
    attempt; the final block belongs to the transfer that produced the file)."""
    lines = stdout.decode(errors="replace").splitlines()[-2:]
    if len(lines) != 2:
        return Served(etag="", last_modified="")
    return Served(etag=normalize_etag(lines[0]), last_modified=lines[1].strip())


def curl_fetch(cfg: S3Config, entry: KeyEntry, dest: Path) -> Served:
    """Download to ``dest``; return the ETag and Last-Modified the response carried. The
    write-out goes to stdout, the body to ``--output``: the two streams cannot mix."""
    url = f"{cfg.base_url}/{entry.key}"
    proc = curl_run(
        curl_base_args(cfg)
        + [
            "--retry",
            "5",
            "--retry-delay",
            "5",
            "--retry-all-errors",
            "--write-out",
            WRITE_OUT,
            url,
            "--output",
            str(dest),
        ],
        curl_auth_stdin(cfg),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"download failed rc={proc.returncode}: "
            f"{proc.stderr.decode(errors='replace')[:300]}"
        )
    return parse_write_out(proc.stdout)


def download_one(
    entry: KeyEntry,
    files_root: Path,
    cfg: S3Config,
    min_free_bytes: int,
    fetch_fn: FetchFn = curl_fetch,
    disk_free_fn: Callable[[Path], int] = free_bytes,
    previous: dict | None = None,
) -> dict:
    """Fetch, verify and move one file into place; return its manifest record.

    The record's ``etag`` and ``last_modified`` are the response's, which must carry both
    and whose ETag must equal the inventory's; a single-part ETag must equal the md5 of
    the bytes. ``previous`` is the key's current manifest record. When its ETag differs
    from the response's and the new bytes differ from its sha256, the vendor restated
    the file: the old bytes (proven equal to the previous sha256) are archived beside the
    new ones, never overwritten, and the record carries a ``supersedes`` block.

    Raises DiskFloorError before fetching if the floor would be breached,
    SupersessionRefusedError when the old bytes cannot be proven, and RuntimeError on any
    transfer or verification failure (the .part file is removed; no manifest record is
    written; the caller's retry pass picks it up).
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
        served = fetch_fn(cfg, entry, part)
        etag = normalize_etag(served.etag)
        if not etag or not served.last_modified:
            raise ServeLabelError(f"{entry.key}: response lacks ETag or Last-Modified")
        if etag != entry.etag:
            raise ServeLabelError(
                f"{entry.key}: response ETag {etag} differs from inventory {entry.etag}; "
                f"refresh the inventory"
            )
        actual = part.stat().st_size
        if actual != entry.size:
            raise RuntimeError(f"size mismatch for {entry.key}: listed {entry.size}, got {actual}")
        rows = gzip_rows(part)
        md5_check = is_single_part_etag(etag)
        digests = file_digests(part, ("sha256", "md5") if md5_check else ("sha256",))
        if md5_check and digests["md5"] != etag:
            raise ServeLabelError(f"{entry.key}: md5 {digests['md5']} differs from ETag {etag}")
        digest = digests["sha256"]
        superseded = supersession(previous, etag, digest, entry, files_root)
        if superseded is not None:
            archive_old_bytes(superseded, dest, files_root.parent)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    record = {
        "dataset": entry.dataset,
        "key": entry.key,
        "path": str(dest.relative_to(files_root)),
        "bytes": entry.size,
        "sha256": digest,
        "rows": rows,
        "etag": etag,
        "etag_md5_verified": md5_check,
        "last_modified": served.last_modified,
        "downloaded_at": format_iso_ts(datetime.now(UTC)),
    }
    if superseded is not None:
        record["supersedes"] = superseded
    return record


def supersession(
    previous: dict | None, etag: str, digest: str, entry: KeyEntry, files_root: Path
) -> dict | None:
    """The ``supersedes`` block when ``previous`` is a different vendor version of the
    key (ETag differs AND the bytes differ), else None. The archive path is
    deterministic, so a rerun after a kill between the archive move and the manifest
    append rebuilds the same block. A new ETag over identical bytes is a repair (logged);
    the same ETag over different bytes is the vendor serving two byte sets under one label
    (logged as an error, the record is still written)."""
    if previous is None:
        return None
    if previous["etag"] == etag:
        if previous["sha256"] != digest:
            log.error(
                "download.same_etag_different_bytes",
                key=entry.key,
                etag=etag,
                previous_sha256=previous["sha256"],
                sha256=digest,
            )
        return None
    if previous["sha256"] == digest:
        log.info("download.new_etag_identical_bytes", key=entry.key, etag=etag)
        return None
    name = f"{entry.filename}.superseded-{previous['etag'][:8]}"
    archive = (
        Path(SUPERSEDED_DIR) / entry.local_path(files_root).relative_to(files_root).parent / name
    )
    return {
        "etag": previous["etag"],
        "sha256": previous["sha256"],
        "bytes": previous["bytes"],
        "last_modified": previous.get("last_modified", ""),
        "downloaded_at": previous["downloaded_at"],
        "path": str(archive),
    }


def archive_old_bytes(block: dict, dest: Path, data_root: Path) -> None:
    """Move the previous version to its archive path after proving it is the recorded one.

    The archive already holding the recorded sha256 means a kill after the move
    preserved the old bytes (``dest`` is then the newer file whose record never landed).
    Anything else that cannot be proven refuses."""
    archive = data_root / block["path"]
    if archive.exists():
        if sha256_file(archive) != block["sha256"]:
            raise SupersessionRefusedError(f"refusing to overwrite superseded archive {archive}")
        return
    if not dest.is_file():
        raise SupersessionRefusedError(
            f"old bytes absent: {dest} is missing and {archive} does not exist"
        )
    if sha256_file(dest) != block["sha256"]:
        raise SupersessionRefusedError(
            f"{dest} does not hold the recorded sha256 {block['sha256']}; "
            f"refusing to archive unproven bytes"
        )
    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(dest, archive)


def _file_defect(path: Path, size: int, sha256: str) -> str | None:
    if not path.is_file():
        return "missing"
    if path.stat().st_size != size or sha256_file(path) != sha256:
        return "mismatch"
    return None


def verify_archive(manifest_path: Path, files_root: Path) -> int:
    """Re-hash every recorded file, and every archived superseded file, against its
    manifest record (bit-rot check).

    The resume law is size-only for speed; this is the slow full check the
    completeness proof ultimately rests on. Returns the defect count."""
    history = load_manifest_history(manifest_path)
    index = {record["key"]: record for record in history}
    archived = {
        record["supersedes"]["path"]: record["supersedes"]
        for record in history
        if record.get("supersedes")
    }
    defects = 0
    for record in index.values():
        problem = _file_defect(files_root / record["path"], record["bytes"], record["sha256"])
        if problem:
            log.error(f"verify.{problem}", key=record["key"], path=record["path"])
            defects += 1
    for path, block in archived.items():
        problem = _file_defect(files_root.parent / path, block["bytes"], block["sha256"])
        if problem:
            log.error(f"verify.superseded_{problem}", path=path)
            defects += 1
    log.info("verify.done", records=len(index), superseded=len(archived), defects=defects)
    print(f"verify: {len(index)} records, {len(archived)} superseded, {defects} defects")
    return defects


def md5_of_record(files_root: Path) -> Callable[[dict], str]:
    return lambda record: file_digests(files_root / record["path"], ("md5",))["md5"]


def verify_etag_archive(manifest_path: Path, files_root: Path, workers: int) -> int:
    """Stream every archived file once and compare md5 with its single-part ETag
    (parallel by file; hashlib releases the GIL). Multipart ETags cannot be checked and
    are counted. Returns the defect count."""
    index = load_manifest(manifest_path)
    single = [r for r in index.values() if is_single_part_etag(r.get("etag", ""))]
    md5_of = md5_of_record(files_root)

    def check(record: dict) -> bool:
        try:
            return md5_of(record) == record["etag"]
        except OSError:
            return False

    defects = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for record, ok in zip(single, executor.map(check, single), strict=True):
            if not ok:
                log.error("verify_etag.mismatch", key=record["key"], etag=record["etag"])
                defects += 1
    unchecked = len(index) - len(single)
    log.info("verify_etag.done", checked=len(single), unchecked=unchecked, defects=defects)
    print(f"verify-etag: {len(single)} md5 checked, {unchecked} not single-part, {defects} defects")
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


def restat(
    args: argparse.Namespace,
    cfg: S3Config,
    manifest_path: Path,
    list_runner: CurlRunner,
) -> int:
    """Re-list the vendor, diff ETag and size against the manifest, write the drift
    report; exit 1 on drift, 2 on a refusal (an ETag-less record). Downloads nothing and
    leaves the inventory alone."""
    listed = [
        entry
        for dataset in args.datasets
        for entry in list_prefix(cfg, dataset, runner=list_runner)
    ]
    index = load_manifest(manifest_path)
    in_scope = {
        entry.key
        for entry in filter_entries(
            list(filter(None, map(parse_key, index))),
            set(args.datasets),
            args.date_from,
            args.date_to,
        )
    }
    try:
        drift = restat_drift({key: index[key] for key in in_scope}, listed)
    except MissingServeFieldsError as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return EXIT_REFUSED
    report_path = args.drift_report or (
        manifest_path.parent / f"etag_drift_{datetime.now(UTC):%Y-%m-%d}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(drift, indent=2) + "\n")
    scoped = filter_entries(listed, set(args.datasets), args.date_from, args.date_to)
    new_keys = len({entry.key for entry in scoped} - set(index))
    log.info("restat.done", checked=len(in_scope), drift=len(drift), new_keys=new_keys)
    print(
        f"restat: {len(in_scope)} keys checked, {len(drift)} drifted, "
        f"{new_keys} new to the vendor; report {report_path}"
    )
    return EXIT_FAILED if drift else 0


@contextmanager
def manifest_lock(manifest_dir: Path) -> Iterator[None]:
    """Exclusive non-blocking flock on the manifest directory: one writer at a time."""
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with (manifest_dir / LOCK_NAME).open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ManifestLockedError(f"another writer holds {manifest_dir / LOCK_NAME}") from error
        yield


def run(
    args: argparse.Namespace,
    cfg: S3Config | None = None,
    list_runner: CurlRunner = curl_run,
    fetch_fn: FetchFn = curl_fetch,
) -> int:
    setup_service_logging(str(REPO_ROOT / "logs" / "massive_download.log"))
    writes = args.migrate_manifest or not (args.verify or args.verify_etag or args.restat)
    if not writes:
        return _dispatch(args, cfg, list_runner, fetch_fn)
    try:
        with manifest_lock(args.manifest_dir):
            return _dispatch(args, cfg, list_runner, fetch_fn)
    except (ManifestLockedError, InventoryScopeError) as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return EXIT_REFUSED


def _dispatch(
    args: argparse.Namespace,
    cfg: S3Config | None,
    list_runner: CurlRunner,
    fetch_fn: FetchFn,
) -> int:
    files_root = args.data_root / "files"
    manifest_dir = args.manifest_dir
    inventory_path = manifest_dir / INVENTORY_NAME
    manifest_path = manifest_dir / MANIFEST_NAME

    if args.verify:
        defects = verify_archive(manifest_path, files_root)
        return EXIT_FAILED if defects else 0
    if args.migrate_manifest:
        try:
            migrate_manifest(
                manifest_path,
                manifest_dir,
                md5_of_record(files_root) if args.verify_etag else None,
            )
        except ManifestJoinError as error:
            print(f"MIGRATION FAILED: {error}", file=sys.stderr)
            return EXIT_FAILED
        return 0
    if args.verify_etag:
        defects = verify_etag_archive(manifest_path, files_root, args.concurrency)
        return EXIT_FAILED if defects else 0

    if cfg is None:
        try:
            cfg = S3Config(_env_file=args.env_file)
        except ValidationError as error:
            fields = sorted({".".join(map(str, item["loc"])) for item in error.errors()})
            raise SystemExit(
                f"missing or invalid MASSIVE_S3 credential fields {fields} in environment "
                f"or {args.env_file}"
            ) from None

    if args.restat:
        return restat(args, cfg, manifest_path, list_runner)

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
    try:
        todo, skipped = plan_downloads(selected, manifest_index, files_root)
    except MissingServeFieldsError as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return EXIT_REFUSED
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
        return EXIT_REFUSED

    done_bytes = 0
    done_files = 0
    started = time.monotonic()
    floor_stopped = False
    refusal: SupersessionRefusedError | None = None

    def execute(batch: list[KeyEntry]) -> list[KeyEntry]:
        nonlocal done_bytes, done_files, floor_stopped, refusal
        failed: list[KeyEntry] = []
        stopped = False
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(
                    download_one,
                    entry,
                    files_root,
                    cfg,
                    min_free_bytes,
                    fetch_fn,
                    previous=manifest_index.get(entry.key),
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
                    except SupersessionRefusedError as error:
                        log.error("supersession.refused", key=entry.key, error=str(error))
                        refusal = error
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
        if not failures or refusal or floor_stopped:
            break
        log.info("retry.pass", attempt=attempt, files=len(failures))
        failures = execute(failures)

    elapsed = time.monotonic() - started
    status = "failure" if (failures or refusal or floor_stopped) else "success"
    JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
    flush_and_shutdown_metrics()
    if floor_stopped:
        log.error("disk.floor_stopped_run")
        print(
            f"REFUSING mid-run: free space reached the {args.min_free_gb} GB floor; "
            f"rerun when space is freed",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if refusal:
        print(f"REFUSING: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    if failures:
        log.error("run.incomplete", remaining=len(failures))
        print(
            f"FAILED after retries: {len(failures)} files; rerun to retry",
            file=sys.stderr,
        )
        return EXIT_FAILED
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
    parser.add_argument(
        "--refresh-inventory",
        action="store_true",
        help="re-list the vendor and rewrite the inventory; unless --inventory-only is "
        "also given the run then goes on to download",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-hash every manifest-recorded file (size + sha256) and exit",
    )
    parser.add_argument(
        "--verify-etag",
        action="store_true",
        help="md5 every archived file against its single-part ETag (parallel, "
        "--concurrency workers); with --migrate-manifest, gate the join on the same check",
    )
    parser.add_argument(
        "--restat",
        action="store_true",
        help="re-list the vendor, diff ETag and size against the manifest, write the "
        "drift report and exit 1 on drift (no downloads)",
    )
    parser.add_argument(
        "--drift-report",
        type=Path,
        default=None,
        help="--restat output path (default <manifest-dir>/etag_drift_<date>.json)",
    )
    parser.add_argument(
        "--migrate-manifest",
        action="store_true",
        help="append ETag and last_modified to pre-ETag manifest records from servetimes_*.jsonl",
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
