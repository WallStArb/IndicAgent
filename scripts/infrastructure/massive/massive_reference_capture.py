"""Raw capture of the Massive REST reference data (todo 600).

Every response body is stored byte for byte (gzip-compressed losslessly) under
``data/massive/reference/<endpoint>/<captured_at>/<key>__pNNNN.json.gz`` and described by one line
in ``data/massive/reference/manifest/<captured_at>.jsonl`` (endpoint, key, page, URL as sent with
any API key stripped, HTTP status, response Date header, bytes, sha256 of the body, fetched_at).
Nothing is parsed or filtered here: typed tables are rebuilt from these files by pure parsers, so a
parser fix never needs a refetch. A re-capture writes a new dated directory.

Phases, in one run: the five list endpoints (tickers active, tickers delisted, splits, dividends,
ipos), then every ticker named in the saved ticker pages through the per-ticker endpoints (overview,
events, short interest, short volume, income statement, balance sheet, cash flow, ratios, float).
A per-ticker key is ``<ticker>@active`` or ``<ticker>@<delisted date>``: tickers are reused, so the
string alone does not name an entity. A delisted name's overview is asked as of its last active day
(the API answers 404 for a delisted ticker without a date).

What counts as a served answer: a 200 that parses as JSON, and on page 1 any other 4xx (a 404 is the
vendor's answer for that key). Anything else is a unit failure and is never recorded as complete: a
200 that is not JSON, a non-200 on a later page (an expired cursor), a redirect (the Authorization
header must never follow one), a ``next_url`` on another host or one already seen, or more than
``MAX_PAGES`` pages. A failed unit is retried from page 1 over its own earlier pages.

Resume law: a (endpoint, key, page) in the manifest whose file on disk still matches its recorded
size and sha256 is skipped (its ``next_url`` is read back from the saved page); a file that does not
match is fetched again. A kill leaves at most a ``.part`` file; a record is appended only after its
file is fsynced into place. One run per capture at a time (an exclusive lock on the manifest).
Pass the same ``--captured-at`` to resume; the default is today's UTC date.

Credentials: ``MASSIVE_API_KEY`` from the environment or ``.env``; it travels only in an
Authorization header inside this process (never in argv, a file or a stored URL).

Usage:
    .venv/bin/python -m scripts.infrastructure.massive.massive_reference_capture \\
        [--captured-at YYYYMMDD] [--concurrency N] [--only name,name] [--ticker-limit N] [--verify]
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import random
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import structlog
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.service_utils import format_iso_ts, setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

REPO_ROOT = Path(__file__).resolve().parents[3]
JOB = "massive-reference-capture"
DEFAULT_CONCURRENCY = 8
DEFAULT_MIN_FREE_GB = 20
MAX_ATTEMPTS = 6
BACKOFF_BASE_S = 2.0
MAX_PAGES = 1000
RETRY_PASSES = 3
RETRY_PASS_COOLDOWN_S = 30.0
PROGRESS_EVERY = 500
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

log = structlog.get_logger("massive_reference_capture")


class AuthError(RuntimeError):
    """401: the key is wrong or expired; every later request would fail the same way."""


class EndpointDenied(RuntimeError):
    """403 on one endpoint: the plan does not entitle it; the others keep running."""

    def __init__(self, endpoint_url: str) -> None:
        super().__init__(f"HTTP 403 for {endpoint_url}")
        self.url = endpoint_url


class DiskFloorError(RuntimeError):
    """Free space fell under the floor mid-run."""


class RestConfig(BaseSettings):
    """MASSIVE_API_KEY, read from the environment or an .env file."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(validation_alias="MASSIVE_API_KEY")
    base_url: str = Field(default="https://api.massive.com", validation_alias="MASSIVE_REST_URL")


@dataclass(frozen=True)
class Endpoint:
    """One endpoint: ``path`` and ``query`` may use ``{ticker}`` for per-ticker endpoints."""

    name: str
    path: str
    query: str = ""
    per_ticker: bool = False
    dated_when_delisted: bool = False


LIST_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("tickers_active", "/v3/reference/tickers", "market=stocks&active=true&limit=1000"),
    Endpoint("tickers_delisted", "/v3/reference/tickers", "market=stocks&active=false&limit=1000"),
    Endpoint("splits", "/stocks/v1/splits", "limit=5000"),
    Endpoint("dividends", "/stocks/v1/dividends", "limit=5000"),
    Endpoint("ipos", "/vX/reference/ipos", "limit=1000"),
)
TICKER_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("overview", "/v3/reference/tickers/{ticker}", "", True, dated_when_delisted=True),
    Endpoint("events", "/vX/reference/tickers/{ticker}/events", "", True),
    Endpoint("short_interest", "/stocks/v1/short-interest", "ticker={ticker}&limit=5000", True),
    Endpoint("short_volume", "/stocks/v1/short-volume", "ticker={ticker}&limit=5000", True),
    Endpoint(
        "income_statements",
        "/stocks/financials/v1/income-statements",
        "tickers={ticker}&limit=1000",
        True,
    ),
    Endpoint(
        "balance_sheets",
        "/stocks/financials/v1/balance-sheets",
        "tickers={ticker}&limit=1000",
        True,
    ),
    Endpoint(
        "cash_flow_statements",
        "/stocks/financials/v1/cash-flow-statements",
        "tickers={ticker}&limit=1000",
        True,
    ),
    Endpoint("ratios", "/stocks/financials/v1/ratios", "ticker={ticker}&limit=1000", True),
    Endpoint("float", "/stocks/vX/float", "ticker={ticker}", True),
)
TICKER_LIST_ENDPOINTS = ("tickers_active", "tickers_delisted")
ALL_ENDPOINT_NAMES = frozenset(e.name for e in LIST_ENDPOINTS + TICKER_ENDPOINTS)
ACTIVE = "active"


@dataclass(frozen=True)
class Response:
    status: int
    date_header: str
    body: bytes
    retry_after: str = ""


@dataclass(frozen=True)
class TickerRow:
    """One row of the saved ticker lists: the ticker and its delisting date (None if active)."""

    ticker: str
    delisted: str | None

    @property
    def key(self) -> str:
        return f"{self.ticker}@{self.delisted or ACTIVE}"


@dataclass(frozen=True)
class Unit:
    """One capture unit: an endpoint for one key, all pages in order."""

    endpoint: Endpoint
    key: str
    ticker: str = ""
    delisted: str | None = None

    def first_url(self, base_url: str) -> str:
        ticker = quote(self.ticker, safe="")
        path = self.endpoint.path.format(ticker=ticker)
        query = self.endpoint.query.format(ticker=ticker)
        if self.endpoint.dated_when_delisted and self.delisted:
            last_active = date.fromisoformat(self.delisted) - timedelta(days=1)
            query = f"date={last_active.isoformat()}"
        return f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")


def list_unit(endpoint: Endpoint) -> Unit:
    return Unit(endpoint, "all")


def ticker_unit(endpoint: Endpoint, row: TickerRow) -> Unit:
    return Unit(endpoint, row.key, row.ticker, row.delisted)


def strip_key(url: str) -> str:
    """The URL as sent, minus any apiKey query parameter (nothing secret is ever stored)."""
    head, sep, query = url.partition("?")
    kept = [pair for pair in query.split("&") if pair and not pair.startswith("apiKey=")]
    return head + (sep + "&".join(kept) if kept else "")


def page_path(root: Path, endpoint: str, captured_at: str, key: str, page: int) -> Path:
    return root / endpoint / captured_at / f"{quote(key, safe='')}__p{page:04d}.json.gz"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: urllib would forward the Authorization header to the new host."""

    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_fetch(cfg: RestConfig, url: str) -> Response:
    """One GET with the key in a header; HTTP error statuses (3xx included) come back as responses."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg.api_key}"})
    try:
        with _OPENER.open(request, timeout=60) as handle:
            headers = handle.headers
            return Response(handle.status, headers.get("Date", ""), handle.read())
    except urllib.error.HTTPError as error:
        headers = error.headers
        return Response(
            error.code, headers.get("Date", ""), error.read(), headers.get("Retry-After", "")
        )


def parse_retry_after(value: str, now: datetime | None = None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or an HTTP date), else None."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (target - (now or datetime.now(UTC))).total_seconds())


class Throttle:
    """A shared pause: one 429 slows every worker, not just the thread that saw it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until = 0.0
        self._lock = threading.Lock()

    def pause(self, seconds: float) -> None:
        with self._lock:
            self._until = max(self._until, self._clock() + seconds)

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._until - self._clock())


@dataclass
class Context:
    """Everything one capture shares across its unit threads."""

    cfg: RestConfig
    root: Path
    captured_at: str
    manifest: Manifest
    fetch_fn: Callable[[str], Response]
    sleep: Callable[[float], None] = time.sleep
    throttle: Throttle = field(default_factory=Throttle)
    denied: set[str] = field(default_factory=set)


def fetch_with_retry(ctx: Context, url: str) -> Response:
    """GET with a shared throttle; retry 429, 5xx and network errors; 401 and 403 raise."""
    safe_url = strip_key(url)
    for attempt in range(MAX_ATTEMPTS):
        wait_s = ctx.throttle.remaining()
        if wait_s:
            ctx.sleep(wait_s)
        delay = BACKOFF_BASE_S * 2**attempt
        try:
            response = ctx.fetch_fn(url)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            log.warning("fetch.network_error", url=safe_url, error=str(error))
        else:
            if response.status == 401:
                raise AuthError(f"HTTP 401 for {safe_url}")
            if response.status == 403:
                raise EndpointDenied(safe_url)
            if 300 <= response.status < 400:
                raise RuntimeError(f"redirect refused (HTTP {response.status}) for {safe_url}")
            if response.status not in RETRY_STATUSES:
                return response
            log.warning("fetch.retry", url=safe_url, status=response.status)
            delay = parse_retry_after(response.retry_after) or delay
        delay *= random.uniform(0.5, 1.0)  # noqa: S311 -- jitter, not security
        ctx.throttle.pause(delay)
    raise RuntimeError(f"gave up after {MAX_ATTEMPTS} attempts: {safe_url}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def next_url_of(body: bytes, base_url: str) -> str | None:
    """``next_url`` from a 200 body; raises if it names another host (a response is untrusted)."""
    document = json.loads(body)
    target = document.get("next_url") if isinstance(document, dict) else None
    if not isinstance(target, str) or not target:
        return None
    if urlsplit(target).hostname != urlsplit(base_url).hostname:
        raise ValueError(f"next_url on another host refused: {strip_key(target)}")
    return target


class Manifest:
    """Append-only manifest for one capture, safe for concurrent appends from the unit threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.records: dict[tuple[str, str, int], dict] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            self._load()

    def _load(self) -> None:
        raw = self.path.read_bytes()
        lines = [line for line in raw.decode().splitlines() if line.strip()]
        for position, line in enumerate(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if position == len(lines) - 1:
                    log.warning("manifest.torn_trailing_line_skipped", line=line[:100])
                    continue
                raise
            self.records[(record["endpoint"], record["key"], record["page"])] = record
        if raw and not raw.endswith(b"\n"):
            with self.path.open("ab") as handle:  # terminate a torn tail so the next line is clean
                handle.write(b"\n")

    def get(self, endpoint: str, key: str, page: int) -> dict | None:
        return self.records.get((endpoint, key, page))

    def append(self, record: dict) -> None:
        with self._lock:
            with self.path.open("a") as handle:
                handle.write(json.dumps(record) + "\n")
            self.records[(record["endpoint"], record["key"], record["page"])] = record


def write_page(path: Path, body: bytes) -> None:
    """Store the body gzip-compressed (deterministic, mtime 0): fsynced .part, then atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    try:
        with part.open("wb") as handle:
            handle.write(gzip.compress(body, mtime=0))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def read_page(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def intact_body(path: Path, record: dict) -> bytes | None:
    """The saved body if the file still matches its manifest record, else None (refetch)."""
    try:
        body = read_page(path)
    except (OSError, EOFError, gzip.BadGzipFile):
        return None
    if len(body) != record["bytes"] or sha256_bytes(body) != record["sha256"]:
        return None
    return body


def served_answer(response: Response, page: int, safe_url: str) -> None:
    """Raise unless this is a recordable answer (module docstring: what counts as served)."""
    if response.status == 200:
        try:
            json.loads(response.body)
        except ValueError as error:
            raise RuntimeError(f"HTTP 200 with a body that is not JSON: {safe_url}") from error
    elif page > 1:
        raise RuntimeError(f"HTTP {response.status} on page {page} (cursor expired?): {safe_url}")


def capture_unit(unit: Unit, ctx: Context, fresh: bool = False) -> int:
    """Capture every page of one unit in order; returns the responses fetched (not resumed).

    ``fresh`` ignores earlier records of the unit and refetches from page 1 (a retry after a
    failure, since a saved ``next_url`` cursor may have expired)."""
    name = unit.endpoint.name
    if name in ctx.denied:
        return 0
    fetched = 0
    url: str | None = unit.first_url(ctx.cfg.base_url)
    seen: set[str] = set()
    page = 1
    while url is not None:
        if url in seen or page > MAX_PAGES:
            raise RuntimeError(f"pagination did not end ({page} pages, repeated cursor?): {name}")
        seen.add(url)
        path = page_path(ctx.root, name, ctx.captured_at, unit.key, page)
        record = None if fresh else ctx.manifest.get(name, unit.key, page)
        body = intact_body(path, record) if record is not None else None
        if body is None:
            response = fetch_with_retry(ctx, url)
            served_answer(response, page, strip_key(url))
            body = response.body
            write_page(path, body)
            ctx.manifest.append(
                {
                    "endpoint": name,
                    "key": unit.key,
                    "page": page,
                    "url": strip_key(url),
                    "status": response.status,
                    "date": response.date_header,
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                    "path": str(path.relative_to(ctx.root)),
                    "fetched_at": format_iso_ts(datetime.now(UTC)),
                }
            )
            fetched += 1
        stored = ctx.manifest.get(name, unit.key, page)
        url = next_url_of(body, ctx.cfg.base_url) if stored and stored["status"] == 200 else None
        page += 1
    return fetched


def ticker_rows(root: Path, captured_at: str) -> list[TickerRow]:
    """Distinct (ticker, delisting date) rows in the saved ticker-list pages, sorted."""
    found: set[TickerRow] = set()
    for name in TICKER_LIST_ENDPOINTS:
        directory = root / name / captured_at
        for path in sorted(directory.glob("*.json.gz")) if directory.is_dir() else ():
            document = json.loads(read_page(path))
            for row in document.get("results", []) if isinstance(document, dict) else []:
                ticker = row.get("ticker") if isinstance(row, dict) else None
                if not ticker:
                    continue
                delisted = row.get("delisted_utc")
                found.add(TickerRow(ticker, delisted[:10] if delisted else None))
    return sorted(found, key=lambda row: (row.ticker, row.delisted or ""))


def check_free_space(root: Path, min_free_gb: int) -> None:
    if shutil.disk_usage(root).free < min_free_gb * (1 << 30):
        raise DiskFloorError(f"free space under {min_free_gb} GB")


def run_units(
    units: Iterable[Unit],
    ctx: Context,
    concurrency: int,
    min_free_gb: int,
    fresh: bool = False,
) -> tuple[int, list[Unit]]:
    """Run units at bounded concurrency with a bounded submit window; returns (fetched, failed)."""
    fetched = 0
    failed: list[Unit] = []
    done = 0
    started = time.monotonic()
    iterator: Iterator[Unit] = iter(units)
    pending: dict = {}
    window = 4 * concurrency
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        try:
            while True:
                while len(pending) < window and (unit := next(iterator, None)) is not None:
                    pending[executor.submit(capture_unit, unit, ctx, fresh)] = unit
                if not pending:
                    break
                finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in finished:
                    unit = pending.pop(future)
                    try:
                        fetched += future.result()
                    except EndpointDenied as error:
                        ctx.denied.add(unit.endpoint.name)
                        log.error("endpoint.denied", endpoint=unit.endpoint.name, url=error.url)
                    except (AuthError, DiskFloorError):
                        raise
                    except Exception as error:  # noqa: BLE001 -- per-unit failure is retryable
                        log.warning(
                            "unit.failed",
                            endpoint=unit.endpoint.name,
                            key=unit.key,
                            error=str(error),
                        )
                        failed.append(unit)
                    done += 1
                    if done % PROGRESS_EVERY == 0:
                        check_free_space(ctx.root, min_free_gb)
                        rate = fetched / max(time.monotonic() - started, 1e-9)
                        log.info(
                            "progress",
                            units_done=done,
                            responses=fetched,
                            per_second=round(rate, 1),
                        )
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    return fetched, failed


def run_with_retries(
    units: list[Unit], ctx: Context, concurrency: int, min_free_gb: int
) -> tuple[int, list[Unit]]:
    """One pass, then up to RETRY_PASSES fresh passes over the failures, each after a cool-down."""
    total, failed = run_units(units, ctx, concurrency, min_free_gb)
    for attempt in range(1, RETRY_PASSES + 1):
        if not failed:
            break
        log.info("retry.pass", attempt=attempt, units=len(failed))
        ctx.sleep(RETRY_PASS_COOLDOWN_S)
        fetched, failed = run_units(failed, ctx, concurrency, min_free_gb, fresh=True)
        total += fetched
    return total, failed


def verify_capture(root: Path, manifest_path: Path) -> int:
    """Re-hash every recorded response against its manifest line; returns the defect count."""
    manifest = Manifest(manifest_path)
    defects = 0
    for record in manifest.records.values():
        path = root / record["path"]
        if not path.is_file():
            log.error("verify.missing", path=record["path"])
            defects += 1
        elif intact_body(path, record) is None:
            log.error("verify.mismatch", path=record["path"])
            defects += 1
    log.info("verify.done", records=len(manifest.records), defects=defects)
    print(f"verify: {len(manifest.records)} records, {defects} defects")
    return defects


def run(
    args: argparse.Namespace,
    cfg: RestConfig | None = None,
    fetch_fn: Callable[[str], Response] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    setup_service_logging(str(REPO_ROOT / "logs" / "massive_reference_capture.log"))
    if cfg is None:
        try:
            cfg = RestConfig(_env_file=args.env_file)
        except ValidationError as error:
            raise SystemExit(
                f"missing MASSIVE_API_KEY in environment or {args.env_file}"
            ) from error
    root = args.data_root / "reference"
    manifest_path = root / "manifest" / f"{args.captured_at}.jsonl"
    if args.verify:
        return 1 if verify_capture(root, manifest_path) else 0
    only = set(args.only.split(",")) if args.only else None
    if only is not None and not only <= ALL_ENDPOINT_NAMES:
        print(f"unknown endpoint(s): {sorted(only - ALL_ENDPOINT_NAMES)}", file=sys.stderr)
        return 2
    if fetch_fn is None:

        def fetch_fn(url: str) -> Response:
            return http_fetch(cfg, url)

    root.mkdir(parents=True, exist_ok=True)
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

    ctx = Context(cfg, root, args.captured_at, Manifest(manifest_path), fetch_fn, sleep)
    list_endpoints = [e for e in LIST_ENDPOINTS if only is None or e.name in only]
    ticker_endpoints = [e for e in TICKER_ENDPOINTS if only is None or e.name in only]
    total = 0
    failed: list[Unit] = []
    try:
        total, failed = run_with_retries(
            [list_unit(e) for e in list_endpoints], ctx, args.concurrency, args.min_free_gb
        )
        if ticker_endpoints and not failed:
            rows = ticker_rows(root, args.captured_at)
            if not rows:
                print("no saved ticker lists to name the per-ticker universe", file=sys.stderr)
                return 1
            if args.ticker_limit:
                rows = rows[: args.ticker_limit]
            log.info("phase.tickers", endpoints=len(ticker_endpoints), tickers=len(rows))
            units = (ticker_unit(e, row) for row in rows for e in ticker_endpoints)
            fetched, failed = run_with_retries(list(units), ctx, args.concurrency, args.min_free_gb)
            total += fetched
        elif ticker_endpoints:
            print(
                "a ticker or list endpoint failed; the per-ticker phase was not started",
                file=sys.stderr,
            )
    except AuthError as error:
        log.error("run.auth_failed", error=str(error))
        print(f"AUTH FAILED: {error}", file=sys.stderr)
        return 3
    except DiskFloorError as error:
        print(f"REFUSING mid-run: {error}", file=sys.stderr)
        return 2
    finally:
        status = "failure" if failed or ctx.denied else "success"
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
        flush_and_shutdown_metrics()
        lock.close()
    print(
        f"done: {total} responses fetched, {len(failed)} units failed, "
        f"denied endpoints {sorted(ctx.denied)}; manifest {manifest_path}"
    )
    return 1 if failed or ctx.denied else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT / "data" / "massive")
    parser.add_argument("--captured-at", default=datetime.now(UTC).strftime("%Y%m%d"))
    parser.add_argument("--only", default=None, help="comma-separated endpoint names")
    parser.add_argument("--ticker-limit", type=int, default=0, help="first N tickers (testing)")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--min-free-gb", type=int, default=DEFAULT_MIN_FREE_GB)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
