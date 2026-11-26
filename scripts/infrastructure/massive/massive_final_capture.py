"""Final raw capture of the Massive REST families the paid plan entitles beyond the reference
capture (owner order 2026-11-26, before the plan lapses about 2026-12-10).

Reuses the reference tool's machinery (``massive_reference_capture``: Endpoint and Unit, bounded
retry with a shared 429 throttle, ``next_url`` pagination, temp-then-rename gzip pages, resume by
manifest, ``verify_capture``). A family is a list of units; every response body is stored byte for
byte under ``data/massive/reference/<endpoint>/<captured_at>/<key>__pNNNN.json.gz`` and described by
one line in ``data/massive/reference/final_manifest/<captured_at>.jsonl``. That directory is not the
reference loader's ``manifest/`` glob: these files are raw only and nothing loads them into the
database. Nothing is parsed or filtered; a re-capture uses a new ``--captured-at`` and never
overwrites.

Families, in capture order (``--only`` picks some; ``--list`` prints the plan):
  economy             four /fed/v1 series, full history, one request each
  news                /v2/reference/news sliced by publication month (follows next_url)
  related_companies   /v1/related-companies/{ticker} for every active ticker of the saved list
  fx_crypto_lists,    fx and crypto ticker lists, then daily aggregates per pair (the plan serves
  fx_crypto_aggs      about two years; a request from 2000 is clamped by the vendor). The vendor
                      answers 429 after about 5 aggregate requests per minute, so this family is
                      paced at one request per 13 s (hours for about 1,700 pairs).
  options_contracts   /v3/reference/options/contracts incl. expired, sliced by expiration date
  filings             10-K sections, risk factors and 8-K text, sliced by filing month

Guards: ``--budget-gb`` caps the bytes this capture writes (checked between chunks of units),
``--min-free-gb`` stops the run when the disk falls under the floor, concurrency defaults to 2, one
capture per ``--captured-at`` (an exclusive lock). 401 stops the run (exit 3); a 403 denies one
endpoint and the rest continue (exit 1 at the end); a unit that fails after the retry passes is
reported, never recorded as complete.

Mirror: ``--mirror-verify`` compares this capture's files on ubuntu1 with the ubuntu2 mirror by
size over ssh (read only); ``--mirror-push`` runs a plain additive rsync of just those files.

Credentials: ``MASSIVE_API_KEY`` through the reference tool's settings (environment or ``.env``);
it travels only in an Authorization header.

Usage:
    .venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 \\
        [--only economy,news] [--concurrency 2] [--budget-gb 250] [--min-free-gb 400]
    .venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 --verify
    .venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 --mirror-verify
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import structlog
from pydantic import ValidationError

from scripts.infrastructure.massive.massive_reference_capture import (
    REPO_ROOT,
    AuthError,
    Context,
    DiskFloorError,
    Endpoint,
    Manifest,
    Response,
    RestConfig,
    Unit,
    check_free_space,
    http_fetch,
    read_page,
    run_with_retries,
    ticker_rows,
    verify_capture,
)
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

JOB = "massive-final-capture"
DEFAULT_CONCURRENCY = 2
DEFAULT_MIN_FREE_GB = 400
DEFAULT_BUDGET_GB = 250
DEFAULT_MIRROR_HOST = "192.168.68.65"
DEFAULT_MIRROR_ROOT = "/home/bg/mirror/dev/indicagent/data/massive/reference"
MIRROR_MIN_SPARE_GB = 40
CHUNK_UNITS = 400
MANIFEST_DIR = "final_manifest"
NEWS_FIRST_MONTH = date(2016, 6, 1)
FILINGS_FIRST_MONTH = date(2000, 1, 1)
AGGS_FROM = "2000-01-01"
# the vendor answered 429 after bursts of 5 aggregate requests, about 5 per minute (2026-11-26)
AGGS_MIN_INTERVAL_S = 13.0
OPTIONS_FIRST_DAY = date(2010, 1, 1)
OPTIONS_FORWARD_DAYS = 1200

log = structlog.get_logger("massive_final_capture")

ECONOMY: tuple[tuple[str, str], ...] = (
    ("economy_treasury_yields", "/fed/v1/treasury-yields"),
    ("economy_inflation", "/fed/v1/inflation"),
    ("economy_inflation_expectations", "/fed/v1/inflation-expectations"),
    ("economy_labor_market", "/fed/v1/labor-market"),
)
# (endpoint name, path, page size, sort field); the vendor accepts only its own sort field per path
FILINGS: tuple[tuple[str, str, int, str], ...] = (
    ("filings_10k_sections", "/stocks/filings/10-K/vX/sections", 100, "period_end"),
    ("filings_risk_factors", "/stocks/filings/vX/risk-factors", 1000, "filing_date"),
    ("filings_8k_text", "/stocks/filings/8-K/vX/text", 100, "filing_date"),
)
FX_CRYPTO_MARKETS = ("fx", "crypto")
FX_CRYPTO_STATES = ("active", "inactive")


@dataclass(frozen=True)
class Plan:
    """What a family needs to name its units: the data root and the capture's dates."""

    root: Path
    captured_at: str
    captured_on: date
    ref_captured_at: str


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return (month_start(day) + timedelta(days=32)).replace(day=1)


def month_slices(first: date, last_exclusive: date) -> list[tuple[str, date, date]]:
    """(key, start, end_exclusive) per calendar month from ``first`` to ``last_exclusive``; the
    final slice is cut at ``last_exclusive`` so a capture never asks beyond its own date."""
    slices = []
    start = month_start(first)
    while start < last_exclusive:
        end = min(next_month(start), last_exclusive)
        slices.append((start.strftime("%Y-%m"), start, end))
        start = next_month(start)
    return slices


def literal_unit(name: str, path: str, query: str, key: str) -> Unit:
    """A unit whose URL is fully formed (the endpoint carries no ``{ticker}`` placeholder)."""
    return Unit(Endpoint(name, path, query), key)


def economy_units(plan: Plan) -> list[Unit]:
    return [literal_unit(name, path, "limit=50000&sort=date.asc", "all") for name, path in ECONOMY]


def news_units(plan: Plan) -> list[Unit]:
    end = plan.captured_on + timedelta(days=1)
    return [
        literal_unit(
            "news",
            "/v2/reference/news",
            f"limit=1000&sort=published_utc&order=asc&published_utc.gte={a}&published_utc.lt={b}",
            key,
        )
        for key, a, b in month_slices(NEWS_FIRST_MONTH, end)
    ]


def related_units(plan: Plan) -> list[Unit]:
    rows = [r for r in ticker_rows(plan.root, plan.ref_captured_at) if r.delisted is None]
    if not rows:
        raise RuntimeError(f"no active tickers saved under capture {plan.ref_captured_at}")
    return [
        literal_unit(
            "related_companies", f"/v1/related-companies/{quote(r.ticker, safe='')}", "", r.key
        )
        for r in rows
    ]


def fx_crypto_list_units(plan: Plan) -> list[Unit]:
    return [
        literal_unit(
            f"{market}_tickers",
            "/v3/reference/tickers",
            f"market={market}&active={str(state == 'active').lower()}&limit=1000",
            state,
        )
        for market in FX_CRYPTO_MARKETS
        for state in FX_CRYPTO_STATES
    ]


def pair_tickers(plan: Plan, market: str) -> list[str]:
    """Distinct tickers over the saved ticker-list pages of one market, sorted."""
    found: set[str] = set()
    for path in sorted((plan.root / f"{market}_tickers" / plan.captured_at).glob("*.json.gz")):
        document = json.loads(read_page(path))
        for row in document.get("results", []) if isinstance(document, dict) else []:
            if isinstance(row, dict) and row.get("ticker"):
                found.add(row["ticker"])
    return sorted(found)


def fx_crypto_aggs_units(plan: Plan) -> list[Unit]:
    end = plan.captured_on.isoformat()
    units = []
    for market in FX_CRYPTO_MARKETS:
        for ticker in pair_tickers(plan, market):
            path = f"/v2/aggs/ticker/{quote(ticker, safe=':')}/range/1/day/{AGGS_FROM}/{end}"
            units.append(literal_unit(f"{market}_aggs", path, "limit=50000&sort=asc", ticker))
    if not units:
        raise RuntimeError("no fx or crypto tickers saved; the list phase did not complete")
    return units


def options_contract_units(plan: Plan) -> list[Unit]:
    """Contracts by expiration date (weekdays): ``@expired`` before the capture date, ``@active``
    after it, both on it (the vendor lists the two states apart). A day is one unit because a
    single expiry day runs to about 320 pages."""
    units = []
    for offset in range((plan.captured_on - OPTIONS_FIRST_DAY).days + OPTIONS_FORWARD_DAYS + 1):
        day = OPTIONS_FIRST_DAY + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for state in ("expired", "active"):
            if (state == "expired" and day > plan.captured_on) or (
                state == "active" and day < plan.captured_on
            ):
                continue
            units.append(
                literal_unit(
                    "options_contracts",
                    "/v3/reference/options/contracts",
                    f"limit=1000&expired={str(state == 'expired').lower()}"
                    f"&expiration_date={day.isoformat()}",
                    f"{day.isoformat()}@{state}",
                )
            )
    return units


def filings_units(plan: Plan) -> list[Unit]:
    end = plan.captured_on + timedelta(days=1)
    return [
        literal_unit(
            name,
            path,
            f"limit={limit}&sort={sort}&order=asc&filing_date.gte={a}&filing_date.lt={b}",
            key,
        )
        for name, path, limit, sort in FILINGS
        for key, a, b in month_slices(FILINGS_FIRST_MONTH, end)
    ]


@dataclass(frozen=True)
class Family:
    name: str
    build: Callable[[Plan], list[Unit]]
    min_interval_s: float = 0.0  # spacing between requests for a family the vendor rate-limits


FAMILIES: tuple[Family, ...] = (
    Family("economy", economy_units),
    Family("news", news_units),
    Family("related_companies", related_units),
    Family("fx_crypto_lists", fx_crypto_list_units),
    Family("fx_crypto_aggs", fx_crypto_aggs_units, AGGS_MIN_INTERVAL_S),
    Family("options_contracts", options_contract_units),
    Family("filings", filings_units),
)
FAMILY_NAMES = tuple(f.name for f in FAMILIES)


def selected_families(only: str | None) -> list[Family]:
    if not only:
        return list(FAMILIES)
    wanted = [n for n in only.split(",") if n]
    unknown = [n for n in wanted if n not in FAMILY_NAMES]
    if unknown:
        raise ValueError(f"unknown family: {unknown}; choose from {list(FAMILY_NAMES)}")
    return [f for f in FAMILIES if f.name in wanted]


def capture_dirs(root: Path, captured_at: str) -> list[Path]:
    """Every endpoint directory of this capture under the reference root, from the manifest."""
    manifest = Manifest(root / MANIFEST_DIR / f"{captured_at}.jsonl")
    return sorted({root / r["path"].split("/")[0] / captured_at for r in manifest.records.values()})


def bytes_on_disk(root: Path, captured_at: str) -> int:
    return sum(
        f.stat().st_size for d in capture_dirs(root, captured_at) for f in d.glob("*.json.gz")
    )


class BudgetExceededError(RuntimeError):
    """The capture's bytes on disk passed ``--budget-gb``."""


class Pacer:
    """Serializes requests at a fixed spacing across all worker threads."""

    def __init__(
        self, fetch_fn: Callable[[str], Response], interval_s: float, sleep, clock
    ) -> None:
        self._fetch, self._interval, self._sleep, self._clock = fetch_fn, interval_s, sleep, clock
        self._next_at = 0.0
        self._lock = threading.Lock()

    def __call__(self, url: str) -> Response:
        with self._lock:
            wait = self._next_at - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._next_at = max(self._next_at, self._clock()) + self._interval
        return self._fetch(url)


def run_family(
    family: Family, plan: Plan, ctx: Context, args: argparse.Namespace
) -> tuple[int, list[Unit]]:
    """Run one family in chunks; the budget is checked between chunks."""
    units = family.build(plan)
    if family.min_interval_s:
        ctx = replace(
            ctx,
            fetch_fn=Pacer(ctx.fetch_fn, family.min_interval_s, ctx.sleep, time.monotonic),
        )
    total = 0
    failed: list[Unit] = []
    for start in range(0, len(units), CHUNK_UNITS):
        fetched, bad = run_with_retries(
            units[start : start + CHUNK_UNITS], ctx, args.concurrency, args.min_free_gb
        )
        total += fetched
        failed += bad
        used = bytes_on_disk(plan.root, plan.captured_at)
        log.info(
            "family.chunk",
            family=family.name,
            done=min(start + CHUNK_UNITS, len(units)),
            of=len(units),
        )
        if used > args.budget_gb * (1 << 30):
            raise BudgetExceededError(f"{used / (1 << 30):.1f} GB written, budget {args.budget_gb}")
    log.info("family.done", family=family.name, units=len(units), responses=total)
    return total, failed


def summarize(root: Path, captured_at: str) -> dict:
    """Counts, bytes and the manifest's own sha256, per endpoint; written beside the manifest."""
    manifest_path = root / MANIFEST_DIR / f"{captured_at}.jsonl"
    per: dict[str, dict] = defaultdict(lambda: {"pages": 0, "keys": set(), "bytes": 0, "gz": 0})
    for record in Manifest(manifest_path).records.values():
        entry = per[record["endpoint"]]
        entry["pages"] += 1
        entry["keys"].add(record["key"])
        entry["bytes"] += record["bytes"]
        path = root / record["path"]
        entry["gz"] += path.stat().st_size if path.is_file() else 0
    summary = {
        "captured_at": captured_at,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "endpoints": {
            name: {**entry, "keys": len(entry["keys"])} for name, entry in sorted(per.items())
        },
    }
    out = root / MANIFEST_DIR / f"{captured_at}.summary.json"
    out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return summary


def local_inventory(root: Path, captured_at: str) -> dict[str, int]:
    """Relative path to size for this capture's pages and its manifest files."""
    files: dict[str, int] = {}
    for d in capture_dirs(root, captured_at):
        for f in d.glob("*.json.gz"):
            files[str(f.relative_to(root))] = f.stat().st_size
    for f in (root / MANIFEST_DIR).glob(f"{captured_at}.*"):
        if f.suffix != ".lock":
            files[str(f.relative_to(root))] = f.stat().st_size
    return files


def remote_inventory(
    host: str, remote_root: str, captured_at: str, dirs: list[str]
) -> dict[str, int]:
    """The same listing on the mirror, one read-only ``find`` over ssh."""
    targets = " ".join([quote(f"{d}/{captured_at}") for d in dirs] + [quote(f"{MANIFEST_DIR}")])
    command = f"cd {quote(remote_root)} && find {targets} -type f -printf '%p\\t%s\\n' 2>/dev/null"
    out = subprocess.run(  # noqa: S603 -- fixed argv, host from our own flag
        ["ssh", "-o", "BatchMode=yes", host, command],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    ).stdout
    files = {}
    for line in out.splitlines():
        name, _, size = line.rpartition("\t")
        if size.isdigit():
            files[name] = int(size)
    return files


def mirror_free_gb(host: str, remote_root: str) -> float:
    out = subprocess.run(  # noqa: S603
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            host,
            f"df -B1 --output=avail {quote(remote_root)} | tail -1",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    ).stdout.strip()
    return int(out) / (1 << 30) if out.isdigit() else -1.0


def mirror_compare(args: argparse.Namespace) -> int:
    root = args.data_root / "reference"
    local = local_inventory(root, args.captured_at)
    dirs = sorted({p.split("/")[0] for p in local if not p.startswith(MANIFEST_DIR)})
    remote = remote_inventory(args.mirror_host, args.mirror_root, args.captured_at, dirs)
    missing = sorted(set(local) - set(remote))
    differ = sorted(p for p in local if p in remote and local[p] != remote[p])
    local_bytes = sum(local.values())
    remote_bytes = sum(remote[p] for p in local if p in remote)
    print(
        f"mirror {args.mirror_host}: local {len(local)} files {local_bytes} bytes; "
        f"mirror has {len(local) - len(missing)} files {remote_bytes} bytes; "
        f"missing {len(missing)}, size differs {len(differ)}"
    )
    for p in (missing + differ)[:10]:
        print(f"  {p}")
    return 1 if missing or differ else 0


def mirror_push(args: argparse.Namespace) -> int:
    """Additive rsync of this capture's files (no --delete); refuses under the spare floor."""
    free = mirror_free_gb(args.mirror_host, args.mirror_root)
    need = sum(local_inventory(args.data_root / "reference", args.captured_at).values()) / (1 << 30)
    if free < need + MIRROR_MIN_SPARE_GB:
        print(f"REFUSING: mirror free {free:.1f} GB, need {need:.1f} + {MIRROR_MIN_SPARE_GB}")
        return 2
    root = args.data_root / "reference"
    listing = "\n".join(sorted(local_inventory(root, args.captured_at))) + "\n"
    result = subprocess.run(  # noqa: S603
        [
            "rsync",
            "-a",
            "--stats",
            "--files-from=-",
            "-e",
            "ssh -o BatchMode=yes",
            f"{root}/",
            f"{args.mirror_host}:{args.mirror_root}/",
        ],
        input=listing,
        capture_output=True,
        text=True,
        check=False,
    )
    print(result.stdout[-600:])
    return result.returncode


def write_summary_line(summary: dict) -> None:
    for name, entry in summary["endpoints"].items():
        print(
            f"  {name}: {entry['keys']} keys, {entry['pages']} pages, {entry['gz']} bytes on disk"
        )


def run(
    args: argparse.Namespace,
    cfg: RestConfig | None = None,
    fetch_fn: Callable[[str], Response] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    setup_service_logging(str(REPO_ROOT / "logs" / "massive_final_capture.log"))
    root = args.data_root / "reference"
    manifest_path = root / MANIFEST_DIR / f"{args.captured_at}.jsonl"
    if args.verify:
        return 1 if verify_capture(root, manifest_path) else 0
    if args.mirror_verify:
        return mirror_compare(args)
    if args.mirror_push:
        return mirror_push(args)
    try:
        families = selected_families(args.only)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if cfg is None:
        try:
            cfg = RestConfig(_env_file=args.env_file)
        except ValidationError as error:
            raise SystemExit(
                f"missing MASSIVE_API_KEY in environment or {args.env_file}"
            ) from error
    if fetch_fn is None:

        def fetch_fn(url: str) -> Response:
            return http_fetch(cfg, url)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lock = (manifest_path.parent / f"{args.captured_at}.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"another capture holds the lock for {args.captured_at}", file=sys.stderr)
        return 2
    try:
        check_free_space(root, args.min_free_gb)
    except DiskFloorError as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return 2
    captured_on = datetime.strptime(args.captured_at, "%Y%m%d").replace(tzinfo=UTC).date()
    plan = Plan(root, args.captured_at, captured_on, args.reference_captured_at or args.captured_at)
    ctx = Context(cfg, root, args.captured_at, Manifest(manifest_path), fetch_fn, sleep)
    failed: list[Unit] = []
    total = 0
    code = 0
    try:
        for family in families:
            fetched, bad = run_family(family, plan, ctx, args)
            total += fetched
            failed += bad
    except AuthError as error:
        print(f"AUTH FAILED: {error}", file=sys.stderr)
        code = 3
    except (DiskFloorError, BudgetExceededError) as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        code = 2
    except RuntimeError as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        code = 2
    finally:
        if root.joinpath(MANIFEST_DIR).is_dir() and manifest_path.is_file():
            write_summary_line(summarize(root, args.captured_at))
        ok = code == 0 and not failed and not ctx.denied
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": "success" if ok else "failure"})
        flush_and_shutdown_metrics()
        lock.close()
    print(
        f"done: {total} responses fetched, {len(failed)} units failed "
        f"{sorted({u.endpoint.name for u in failed})}, denied {sorted(ctx.denied)}"
    )
    return code or (1 if failed or ctx.denied else 0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT / "data" / "massive")
    parser.add_argument("--captured-at", default=datetime.now(UTC).strftime("%Y%m%d"))
    parser.add_argument(
        "--reference-captured-at",
        default=None,
        help="the reference capture whose ticker list names related_companies (default: same date)",
    )
    parser.add_argument("--only", default=None, help=f"comma-separated of {list(FAMILY_NAMES)}")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--min-free-gb", type=int, default=DEFAULT_MIN_FREE_GB)
    parser.add_argument("--budget-gb", type=int, default=DEFAULT_BUDGET_GB)
    parser.add_argument("--verify", action="store_true", help="re-hash every recorded page")
    parser.add_argument("--mirror-verify", action="store_true", help="compare with the mirror")
    parser.add_argument("--mirror-push", action="store_true", help="additive rsync to the mirror")
    parser.add_argument("--mirror-host", default=DEFAULT_MIRROR_HOST)
    parser.add_argument("--mirror-root", default=DEFAULT_MIRROR_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
