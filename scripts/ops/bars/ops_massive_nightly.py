"""Massive nightly leaf: keep the flat-file archive and its raw load current, no manual step.

One night is: list the vendor, download the day files the manifest lacks, then load the months
those files touched into ohlcv_raw (vendor massive), 1d then 5m, through the existing loader. The
vendor posts a day's file the next calendar day, so the timer fires around 12:00 UTC.

The window is derived, never remembered, so a missed night heals itself:

- fetch: every vendor key absent from the manifest, whatever its date, one day at a time. A day
  with no key (weekend, holiday, a file not yet posted) is not an error.
  A failed download leaves the manifest where it was, so the same window is asked again.
- load: per timeframe, the months from the month of the day after the newest Massive raw day
  through the newest archived day (``months_to_load``), never an earlier month. A month that fails
  stops that timeframe, so raw never advances past it and the months at or after raw+1 are asked
  again.
- late keys: a fetched day older than that first month (a hole or a late-posted historical day) is
  fetched and verified, never loaded: a reload of an old month under today's identity map is a
  lead decision. It is logged, written to ``late_keys_<UTC date>.json`` beside the manifest, and
  the night exits 1 with status ``manual_load`` after the recent months have loaded.

Drift is reported, never acted on: every listed key's ETag and size is compared with the manifest
(``md.restat_drift``); a difference is not downloaded or loaded. The report goes to
``etag_drift_<UTC date>.json`` beside the manifest, the run counts as status ``drift`` and exits 0,
because the archive as served is correct; a repost is a lead decision (a manual ``--restat``).

Refusals, all exit 1 with a loud log and nothing advanced: the quiet check fails, at the start and
again before the load (the step 7 interlock the ticker entity map install uses: no Massive loader
or nightly process, no Massive load row in the last 30 minutes); a blank ETag in the listing or
the manifest; a fetched file whose manifest record does not match the listing; any download or load
step fails. Dry run is the default and still lists the vendor (a read); it downloads and writes
nothing, and prints the window.

The load uses the newest installed identity map (the loader's default); this leaf never picks a
map. Disk headroom: ``--min-free-gb`` for the download, the loader's own APR floor for the load.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

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


def first_loadable_month(raw_newest: date) -> date:
    """First day of the month holding the day after the newest raw day: nothing older loads."""
    return (raw_newest + timedelta(days=1)).replace(day=1)


def months_to_load(raw_newest: date | None, archived_last: date) -> list[tuple[int, int]]:
    """Calendar months (year, month), oldest first, from the month of the day after the newest raw
    day through the newest archived day; empty when raw is current. An empty raw is a refusal
    upstream, not a full-history load."""
    if raw_newest is None or archived_last <= raw_newest:
        return []
    day, months = first_loadable_month(raw_newest), []
    while (day.year, day.month) <= (archived_last.year, archived_last.month):
        months.append((day.year, day.month))
        day = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return months


def late_keys(todo: list[md.KeyEntry], raw: dict[str, date | None]) -> list[dict]:
    """Fetched keys dated before their timeframe's first loadable month."""
    return [
        {"key": e.key, "dataset": e.dataset, "day": e.date, "month": e.date[:7]}
        for tf, dataset in _TIMEFRAME_DATASET.items()
        for e in todo
        if e.dataset == dataset
        and raw[tf] is not None
        and date.fromisoformat(e.date) < first_loadable_month(raw[tf])
    ]


def absent_from_manifest(
    entries: list[md.KeyEntry], manifest: dict[str, dict]
) -> list[md.KeyEntry]:
    """Every listed key the manifest has no record of, whatever its date: a day that failed
    earlier or was posted late is as missing as a new one. A key already recorded is never
    refetched here, even under a new ETag or size (that is drift, reported)."""
    return [e for e in entries if e.key not in manifest]


@dataclass(frozen=True)
class Steps:
    """The night's effects, injected so the decision logic runs on fakes (no network, no DB)."""

    vendor_entries: Callable[[], list[md.KeyEntry]]
    archived_last: Callable[[str], date]  # newest manifest file day of a dataset
    to_download: Callable[[list[md.KeyEntry]], list[md.KeyEntry]]
    drift: Callable[[list[md.KeyEntry]], list[dict]]  # md.restat_drift rows
    write_report: Callable[[str, list[dict]], Path]  # (name, rows) -> etag_drift / late_keys file
    unverified: Callable[[list[md.KeyEntry]], list[str]]  # window keys without a matching record
    raw_newest: Callable[[str], date | None]  # newest Massive raw day of a timeframe
    require_quiet: Callable[[], None]  # raises InstallRefused
    download: Callable[[str, Window], int]  # (dataset, days) -> 0 on success
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


def _pending(
    steps: Steps, raw: dict[str, date | None], todo: list[md.KeyEntry]
) -> dict[str, list[tuple[int, int]]]:
    """Per timeframe, the months to load once ``todo`` is in the manifest."""
    reach = _reach(steps, todo)
    return {tf: months_to_load(raw[tf], reach[tf]) for tf in _LOAD_ORDER}


def _refused_not_quiet(steps: Steps, out: Callable[[str], None], at: str) -> bool:
    try:
        steps.require_quiet()
    except InstallRefused as error:
        log.error("night.refused_not_quiet", at=at, error=str(error))
        out(f"REFUSING ({at}): {error}")
        return True
    return False


class Night(NamedTuple):
    """The night's exit code and its metric status (success, drift, manual_load, partial)."""

    code: int
    status: str


def run_night(steps: Steps, *, apply: bool, out: Callable[[str], None] = print) -> Night:
    """One night; code 0 when current or done (status drift when the vendor changed a key already
    archived), 1 on any refusal or partial result."""
    try:
        entries = steps.vendor_entries()
        drift = steps.drift(entries)
        todo = steps.to_download(entries)
    except md.MissingServeFieldsError as error:
        log.error("night.missing_etag", error=str(error))
        out(f"REFUSING: {error}")
        return Night(1, "partial")
    status = "drift" if drift else "success"
    if drift:
        log.warning("night.etag_drift", keys=len(drift), first=drift[0]["key"])
        out(f"drift: {len(drift)} listed keys differ from the manifest; none downloaded or loaded")
        if apply:
            out(f"drift report: {steps.write_report("etag_drift", drift)}")
    raw = {tf: steps.raw_newest(tf) for tf in _LOAD_ORDER}
    empty = [tf for tf, day in raw.items() if day is None]
    if empty:
        out(f"REFUSING: no Massive raw rows for {empty}; the first load is a step 7 job")
        return Night(1, "partial")
    late = late_keys(todo, raw)
    pending = _pending(steps, raw, todo)
    out(f"fetch: {len(todo)} files; raw newest {raw}; months to load {pending}")
    if not todo and not any(pending.values()):
        out("nothing new: the archive and raw are current")
        log.info("night.current")
        return Night(0, status)
    if not apply:
        if late:
            out(f"late keys: {len(late)} would be fetched and not loaded (manual_load)")
        out("dry run: nothing downloaded or loaded (--apply to run)")
        return Night(0, status)

    if _refused_not_quiet(steps, out, "start"):
        return Night(1, "partial")
    late_by_key = {row["key"]: row for row in late}
    fetched_late: list[dict] = []
    try:
        # One day at a time: a day's request range holds only absent keys, so a drifted key between
        # two fetched days is never swept into a refetch.
        for e in sorted(todo, key=lambda e: (e.dataset, e.date)):
            day = date.fromisoformat(e.date)
            code = steps.download(e.dataset, Window(day, day))
            bad = steps.unverified([e])
            if code != 0 or bad:
                log.error("night.download_incomplete", key=e.key, exit=code, unverified=bad)
                out(f"FAILED: {e.key} download exit {code}, unverified {len(bad)}; no load")
                return Night(1, "partial")
            if e.key in late_by_key:
                fetched_late.append(late_by_key[e.key])
        pending = _pending(steps, raw, todo)
        # The download can take hours; a map install may have started since the first check.
        if any(pending.values()) and _refused_not_quiet(steps, out, "before load"):
            return Night(1, "partial")
        failed = False
        for tf in _LOAD_ORDER:
            for year, month in pending[tf]:
                code = steps.load(tf, year, month)
                log.info("night.load", timeframe=tf, year=year, month=month, exit=code)
                if code != 0:
                    failed = True
                    out(f"FAILED: {tf} {year}-{month:02d} load exit {code}; later {tf} months wait")
                    break  # raw must not advance past a month that did not load
        if failed:
            return Night(1, "partial")
        if fetched_late:
            return Night(1, "manual_load")
        return Night(0, status)
    finally:
        # Every exit after a fetch reports the late keys it landed: next night they are in the
        # manifest, no longer absent, so this is their only record.
        if fetched_late:
            for row in fetched_late:
                log.error("night.late_key_not_loaded", **row)
            report = steps.write_report("late_keys", fetched_late)
            out(f"late keys: {len(fetched_late)} fetched, not loaded; report {report}")


def _archived_last(manifest_path: Path) -> Callable[[str], date]:
    return lambda dataset: last_file_day(manifest_path.read_bytes(), dataset)


def build_steps(args: argparse.Namespace) -> Steps:
    """The real effects: vendor listing and download through massive_download, raw reads through
    psycopg, loads through the loader's run."""
    manifest_dir = args.manifest_dir
    manifest_path = manifest_dir / md.MANIFEST_NAME
    cfg = md.S3Config(_env_file=args.env_file)
    datasets = list(md.DATASETS)

    def vendor_entries() -> list[md.KeyEntry]:
        if args.apply:
            with md.manifest_lock(manifest_dir):
                entries = md.ensure_inventory(manifest_dir / md.INVENTORY_NAME, cfg, datasets, True)
        else:
            entries = [e for ds in datasets for e in md.list_prefix(cfg, ds)]  # a read only
        for entry in entries:
            if not entry.etag:
                raise md.MissingServeFieldsError(f"listing entry {entry.key} has no ETag")
        return entries

    def drift(entries: list[md.KeyEntry]) -> list[dict]:
        return md.restat_drift(md.load_manifest(manifest_path), entries)

    def write_report(name: str, rows: list[dict]) -> Path:
        path = manifest_dir / f"{name}_{datetime.now(UTC):%Y-%m-%d}.json"
        path.write_text(json.dumps(rows, indent=2) + "\n")
        return path

    def to_download(entries: list[md.KeyEntry]) -> list[md.KeyEntry]:
        return absent_from_manifest(entries, md.load_manifest(manifest_path))

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

    def download(dataset: str, window: Window) -> int:
        dl_args = argparse.Namespace(
            data_root=args.data_root,
            manifest_dir=manifest_dir,
            datasets=[dataset],  # its days are all past its manifest, so none is a repost
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
        # the leaf flushes once, at its end, after its own completion count
        return md.run(dl_args, cfg, emit_metrics=False)

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
        vendor_entries=vendor_entries,
        archived_last=_archived_last(manifest_path),
        to_download=to_download,
        drift=drift,
        write_report=write_report,
        unverified=unverified,
        raw_newest=raw_newest,
        require_quiet=require_quiet,
        download=download,
        load=load,
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
        code, status = run_night(build_steps(args), apply=args.apply)
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
