"""Massive nightly leaf: keep the flat-file archive and its raw load current, no manual step.

One night is: list the vendor, download the day files the manifest lacks, then load the months
those files touched into ohlcv_raw (vendor massive), 1d then 5m, through the existing loader. The
vendor posts a day's file the next calendar day, so the timer fires around 12:00 UTC.

The window is derived, never remembered, so a missed night heals itself:

- fetch: from the day after the oldest per-dataset last archived day in the manifest through the
  vendor's newest key (``fetch_window``). A day with no key (weekend, holiday, a file not yet
  posted) is not an error. A failed download leaves the manifest where it was, so the same window
  is asked again.
- load: per timeframe, the months from the day after the newest Massive raw day through the
  newest archived day (``months_to_load``). A load that failed leaves raw where it was, so the
  months are asked again; the loader is last-wins, so a reload is safe.

Refusals, all exit 1 with a loud log and nothing advanced: the quiet check fails (the step 7
interlock the ticker entity map install uses: no Massive loader process, no Massive load row in the
last 30 minutes); a file in the window has no manifest record whose ETag matches the vendor
listing (an unverified file is never loaded); any download or load step fails. Exit 0 only when
the night is current, or everything it set out to do is done. Dry run is the default and still
lists the vendor (a read); it downloads and writes nothing, and prints the window.

The load uses the newest installed identity map (the loader's default); this leaf never picks a
map. Disk headroom: ``--min-free-gb`` for the download, the loader's own APR floor for the load.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import asyncpg
import psycopg
import structlog

from scripts.infrastructure.massive import massive_download as md
from scripts.ops.bars import ops_massive_load as loader
from scripts.ops.bars.ops_massive_policy_plan import last_file_day
from services.ticker_entity_map_writer import InstallRefused, require_massive_quiet
from src.config.settings import get_settings
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.capture_freshness import session_date_of
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    JOB_DURATION_SECONDS,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers

# Matches the systemd unit suffix (indicagent-massive-nightly), the job label every oneshot emits.
_JOB = "massive-nightly"
_TIMEFRAME_DATASET = {"1d": "day_aggs_v1", "5m": "minute_aggs_v1"}
_LOAD_ORDER = ("1d", "5m")  # daily first: 1d is the canonical series, 5m the liquidity tier
_LOG_FILE = "logs/ops_massive_nightly.log"

log = structlog.get_logger("ops_massive_nightly")


@dataclass(frozen=True)
class Window:
    """Inclusive file-day range to fetch."""

    first: date
    last: date


def fetch_window(archived_last: Sequence[date], vendor_newest: date | None) -> Window | None:
    """The days to fetch, or None when the archive already reaches the vendor's newest key.

    Starts after the OLDEST dataset's last archived day, so a day one dataset posted and the other
    did not yet is asked again the next night."""
    if vendor_newest is None:
        return None
    first = min(archived_last) + timedelta(days=1)
    return Window(first, vendor_newest) if first <= vendor_newest else None


def months_to_load(raw_newest: date | None, archived_last: date) -> list[tuple[int, int]]:
    """Calendar months (year, month), oldest first, between the day after the newest raw day and
    the newest archived day; empty when raw is current. An empty raw is a refusal upstream, not a
    full-history load."""
    if raw_newest is None or archived_last <= raw_newest:
        return []
    day, months = raw_newest + timedelta(days=1), []
    while (day.year, day.month) <= (archived_last.year, archived_last.month):
        months.append((day.year, day.month))
        day = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return months


@dataclass(frozen=True)
class Steps:
    """The night's effects, injected so the decision logic runs on fakes (no network, no DB)."""

    vendor_entries: Callable[[], list[md.KeyEntry]]
    archived_last: Callable[[str], date]  # newest manifest file day of a dataset
    to_download: Callable[[list[md.KeyEntry]], list[md.KeyEntry]]
    unverified: Callable[[list[md.KeyEntry]], list[str]]  # window keys without a matching record
    raw_newest: Callable[[str], date | None]  # newest Massive raw day of a timeframe
    require_quiet: Callable[[], None]  # raises InstallRefused
    download: Callable[[Window], int]  # 0 on success
    load: Callable[[str, int, int], int]  # (timeframe, year, month) -> 0 on success


def _reach(steps: Steps, fetched: list[md.KeyEntry]) -> dict[str, date]:
    """Per timeframe, the newest archived day once ``fetched`` is in the manifest."""
    return {
        tf: max(
            [steps.archived_last(ds)]
            + [date.fromisoformat(e.date) for e in fetched if e.dataset == ds]
        )
        for tf, ds in _TIMEFRAME_DATASET.items()
    }


def run_night(steps: Steps, *, apply: bool, out: Callable[[str], None] = print) -> int:
    """One night; 0 when current or done, 1 on any refusal or partial result."""
    entries = steps.vendor_entries()
    newest = max((date.fromisoformat(e.date) for e in entries), default=None)
    archived = [steps.archived_last(ds) for ds in _TIMEFRAME_DATASET.values()]
    window = fetch_window(archived, newest)
    in_window = (
        [e for e in entries if window.first <= date.fromisoformat(e.date) <= window.last]
        if window
        else []
    )
    todo = steps.to_download(in_window)
    raw = {tf: steps.raw_newest(tf) for tf in _LOAD_ORDER}
    empty = [tf for tf, day in raw.items() if day is None]
    if empty:
        out(f"REFUSING: no Massive raw rows for {empty}; the first load is a step 7 job")
        return 1
    reach = _reach(steps, todo)
    pending = {tf: months_to_load(raw[tf], reach[tf]) for tf in _LOAD_ORDER}
    shown = f"{window.first}..{window.last}" if window else "none"
    out(f"window: fetch {shown}; {len(todo)} files to download (vendor newest {newest})")
    out(f"raw newest: {raw}; months to load: {pending}")
    if not todo and not any(pending.values()):
        out("nothing new: the archive and raw are current")
        log.info("night.current", vendor_newest=str(newest))
        return 0
    if not apply:
        out("dry run: nothing downloaded or loaded (--apply to run)")
        return 0

    try:
        steps.require_quiet()
    except InstallRefused as error:
        log.error("night.refused_not_quiet", error=str(error))
        out(f"REFUSING: {error}")
        return 1

    failed = False
    if todo:
        code = steps.download(window)
        bad = steps.unverified(in_window)
        if code != 0 or bad:
            log.error("night.download_incomplete", exit=code, unverified=bad[:10])
            out(f"FAILED: download exit {code}; {len(bad)} window files unverified; no load")
            return 1
        pending = {tf: months_to_load(raw[tf], _reach(steps, [])[tf]) for tf in _LOAD_ORDER}
    for tf in _LOAD_ORDER:
        for year, month in pending[tf]:
            code = steps.load(tf, year, month)
            log.info("night.load", timeframe=tf, year=year, month=month, exit=code)
            if code != 0:
                failed = True
                out(f"FAILED: {tf} {year}-{month:02d} load exit {code}")
    return 1 if failed else 0


def _archived_last(manifest_path: Path) -> Callable[[str], date]:
    return lambda dataset: last_file_day(manifest_path.read_bytes(), dataset)


def build_steps(args: argparse.Namespace) -> Steps:
    """The real effects: vendor listing and download through massive_download, raw reads through
    psycopg, loads through the loader's run."""
    manifest_dir = args.manifest_dir
    manifest_path = manifest_dir / md.MANIFEST_NAME
    files_root = args.data_root / "files"
    cfg = md.S3Config(_env_file=args.env_file)
    datasets = list(md.DATASETS)

    def vendor_entries() -> list[md.KeyEntry]:
        if args.apply:
            with md.manifest_lock(manifest_dir):
                return md.ensure_inventory(manifest_dir / md.INVENTORY_NAME, cfg, datasets, True)
        return [e for ds in datasets for e in md.list_prefix(cfg, ds)]  # a read; writes nothing

    def to_download(entries: list[md.KeyEntry]) -> list[md.KeyEntry]:
        return md.plan_downloads(entries, md.load_manifest(manifest_path), files_root)[0]

    def unverified(entries: list[md.KeyEntry]) -> list[str]:
        index = md.load_manifest(manifest_path)
        return [e.key for e in entries if index.get(e.key, {}).get("etag") != e.etag]

    def raw_newest(timeframe: str) -> date | None:
        with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
            row = conn.execute(
                'SELECT max("timestamp") FROM ohlcv_raw WHERE vendor = %s AND timeframe = %s',
                ("massive", timeframe),
            ).fetchone()
        return session_date_of(row[0]) if row and row[0] else None

    def require_quiet() -> None:
        async def check() -> None:
            conn = await asyncpg.connect(get_settings().database_url)
            try:
                await require_massive_quiet(conn)
            finally:
                await conn.close()

        asyncio.run(check())

    def download(window: Window) -> int:
        dl_args = argparse.Namespace(
            data_root=args.data_root,
            manifest_dir=manifest_dir,
            datasets=datasets,
            date_from=window.first.isoformat(),
            date_to=window.last.isoformat(),
            inventory_only=False,
            refresh_inventory=False,  # vendor_entries just wrote it
            verify=False,
            verify_etag=False,
            restat=False,
            drift_report=None,
            migrate_manifest=False,
            env_file=args.env_file,
            concurrency=args.concurrency,
            min_free_gb=args.min_free_gb,
        )
        # md.run ends with flush_and_shutdown_metrics, which would close the meter before this
        # leaf's own completion count; the leaf flushes once, at its end.
        with mock.patch.object(md, "flush_and_shutdown_metrics", lambda *_a, **_k: None):
            return md.run(dl_args, cfg)

    def load(timeframe: str, year: int, month: int) -> int:
        return loader.run(
            argparse.Namespace(
                timeframe=timeframe,
                years=[year],
                month=month,
                gap_list=None,  # the newest installed identity map
                out=None,
                apply=True,
                all_tickers=False,
            )
        )

    return Steps(
        vendor_entries,
        _archived_last(manifest_path),
        to_download,
        unverified,
        raw_newest,
        require_quiet,
        download,
        load,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    parser.add_argument("--data-root", type=Path, default=md.REPO_ROOT / "data" / "massive")
    parser.add_argument("--manifest-dir", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=md.REPO_ROOT / ".env")
    parser.add_argument("--concurrency", type=int, default=md.DEFAULT_CONCURRENCY)
    parser.add_argument("--min-free-gb", type=int, default=md.DEFAULT_MIN_FREE_GB)
    args = parser.parse_args(argv)
    args.manifest_dir = args.manifest_dir or args.data_root / "manifest"

    setup_service_logging(_LOG_FILE)
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError as error:
        # A night must not die with its collector; the miss shows as an absent completion.
        print(f"otel init failed, running without metrics: {error}", file=sys.stderr)
    started, status, code = time.monotonic(), "failure", 1
    try:
        code = run_night(build_steps(args), apply=args.apply)
        status = "success" if code == 0 else "partial"
    except Exception:
        log.exception("night.crashed")
        raise
    finally:
        attrs = {"job": _JOB, "status": status}
        JOB_COMPLETED_TOTAL.add(1, attrs)
        JOB_DURATION_SECONDS.record(time.monotonic() - started, attrs)
        flush_and_shutdown_metrics()
    return code


if __name__ == "__main__":
    sys.exit(main())
