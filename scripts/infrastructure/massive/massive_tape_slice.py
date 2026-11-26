"""Capture a cost-calibration tape slice: Massive trades_v1 and quotes_v1 for chosen sessions.

Raw files only (todo 600, owner ruling 2026-11-26): the slice calibrates spread and impact for the
promotion cost gate. Files land in ``data/massive/tapes/<family>/<yyyy>/<mm>/<day>.csv.gz`` with one
manifest line each (size, ETag, last-modified, sha256). The slice stays on ubuntu1; the nightly
mirror excludes it. A rerun skips files the manifest already records, so a killed run resumes.

    massive_tape_slice --last-sessions 20            # list and size, nothing downloaded
    massive_tape_slice --last-sessions 20 --apply    # download
    massive_tape_slice --days 2026-11-17,2026-11-18 --apply
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from scripts.infrastructure.massive import massive_download as md
from src.core.service_utils import format_iso_ts
from src.intelligence.bars.sessions import nyse_sessions

REPO_ROOT = Path(__file__).resolve().parents[3]
TAPES = REPO_ROOT / "data/massive/tapes"
FAMILIES = ("trades_v1", "quotes_v1")
LOOKBACK_DAYS = 45  # calendar window searched for the last N listed sessions
MAX_ATTEMPTS = 8
RETRY_CODES = ("429", "503", "502", "500", "000")
_LISTING = re.compile(
    r"<Key>([^<]+)</Key>.*?<LastModified>([^<]+)</LastModified>"
    r"<ETag>&quot;([^&]+)&quot;</ETag><Size>(\d+)</Size>",
    flags=re.S,
)
_lock = threading.Lock()


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def tape_key(family: str, day: date) -> str:
    return f"us_stocks_sip/{family}/{day.year}/{day.month:02d}/{day}.csv.gz"


def local_path(key: str) -> Path:
    return TAPES / key.removeprefix("us_stocks_sip/")


def pick_last_listed(sessions: list[date], listed: set[date], count: int) -> list[date]:
    """The last ``count`` sessions whose files are published, oldest first."""
    return [day for day in sessions if day in listed][-count:]


def _s3(
    cfg: md.S3Config, suffix: str, extra: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[bytes]:
    args = (
        [a for a in md.curl_base_args(cfg) if a != "--fail"]
        + list(extra)
        + [f"{cfg.base_url}{suffix}"]
    )
    return subprocess.run(args, input=md.curl_auth_stdin(cfg), capture_output=True, check=False)


@dataclass(frozen=True)
class TapeFile:
    """One listed bucket key: what the manifest records before the bytes are hashed."""

    key: str
    day: date
    family: str
    size: int
    etag: str
    last_modified: str


def list_file(cfg: md.S3Config, family: str, day: date) -> TapeFile | None:
    key = tape_key(family, day)
    body = _s3(cfg, f"?list-type=2&prefix={quote(key, safe='')}&max-keys=1").stdout.decode()
    match = _LISTING.search(body)
    if not match or match.group(1) != key:
        return None
    return TapeFile(key, day, family, int(match.group(4)), match.group(3), match.group(2))


def list_days(cfg: md.S3Config, days: list[date]) -> dict[date, list[TapeFile]]:
    """Published files per day; a day missing either family is absent."""
    listed: dict[date, list[TapeFile]] = {}
    for day in days:
        files = [list_file(cfg, family, day) for family in FAMILIES]
        if all(files):
            listed[day] = [f for f in files if f]
    return listed


def download(cfg: md.S3Config, item: TapeFile, min_free_bytes: int) -> str | None:
    """Fetch one key to its path with resume; return the status, or None when it failed."""
    out = local_path(item.key)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size == item.size:
        return "present"
    part = out.with_suffix(out.suffix + ".part")
    for attempt in range(MAX_ATTEMPTS):
        if shutil.disk_usage(TAPES).free < min_free_bytes + item.size:
            raise SystemExit(f"disk low before {item.key}")
        proc = _s3(cfg, "/" + quote(item.key), ("-C", "-", "-o", str(part), "-w", "%{http_code}"))
        code = proc.stdout.decode().strip()[-3:]
        have = part.stat().st_size if part.exists() else 0
        if code in ("200", "206", "416") and have == item.size:
            part.rename(out)
            return "downloaded"
        log(f"{item.key} attempt {attempt} http {code} size {have}/{item.size}")
        if code in RETRY_CODES:
            time.sleep(min(600, 30 * 2**attempt))
        elif code not in ("200", "206"):
            part.unlink(missing_ok=True)
            time.sleep(30)
    return None


def fetch_day(cfg: md.S3Config, files: list[TapeFile], done: set[str], min_free_bytes: int) -> None:
    for item in files:
        if item.key in done:
            continue
        status = download(cfg, item, min_free_bytes)
        if status is None:
            log(f"FAILED {item.key}")
            continue
        record = {
            **asdict(item),
            "day": str(item.day),
            "sha256": md.sha256_file(local_path(item.key)),
            "status": status,
            "recorded_at": format_iso_ts(datetime.now(UTC)),
        }
        with _lock, (TAPES / "manifest.jsonl").open("a") as manifest:
            manifest.write(json.dumps(record) + "\n")
        log(f"done {item.key} {item.size / 1e9:.2f} GB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument(
        "--last-sessions", type=int, help="the last N sessions whose tapes are published"
    )
    pick.add_argument("--days", help="comma-separated YYYY-MM-DD sessions")
    parser.add_argument(
        "--apply", action="store_true", help="download; without it, list and size only"
    )
    parser.add_argument(
        "--cap-gb", type=int, default=400, help="refuse when the new files exceed this"
    )
    parser.add_argument("--min-free-gb", type=int, default=400)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    args = parser.parse_args(argv)

    cfg = md.S3Config(_env_file=args.env_file)  # type: ignore[call-arg]
    TAPES.mkdir(parents=True, exist_ok=True)
    manifest = TAPES / "manifest.jsonl"
    done = (
        {json.loads(line)["key"] for line in manifest.read_text().splitlines()}
        if manifest.exists()
        else set()
    )
    if args.days:
        wanted = [date.fromisoformat(text) for text in args.days.split(",")]
    else:
        today = date.today()
        wanted = sorted(nyse_sessions(today - timedelta(days=LOOKBACK_DAYS), today))
    listed = list_days(cfg, wanted)
    if args.days and len(listed) < len(wanted):
        log(f"not listed: {[str(d) for d in wanted if d not in listed]}")
        return 2
    days = pick_last_listed(wanted, set(listed), args.last_sessions or len(wanted))
    new_bytes = sum(f.size for day in days for f in listed[day] if f.key not in done)
    log(
        f"sessions {[str(d) for d in days]}; {2 * len(days)} files, {new_bytes / 1e9:.1f} GB new (cap {args.cap_gb})"
    )
    if new_bytes > args.cap_gb * 10**9:
        log("over cap, nothing downloaded")
        return 3
    if not args.apply:
        return 0
    with ThreadPoolExecutor(args.workers) as pool:
        list(
            pool.map(lambda day: fetch_day(cfg, listed[day], done, args.min_free_gb * 10**9), days)
        )
    missing = [f.key for day in days for f in listed[day] if not local_path(f.key).exists()]
    log(f"slice finished; {len(missing)} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
