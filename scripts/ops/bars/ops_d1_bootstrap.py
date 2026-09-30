"""D1 bootstrap (phase 185 plan 15, D-05, D-22): the stored corpus plus one paired fresh fetch.

Two subcommands:

  legacy-import  No IBKR. Every stored ibkr_named 1d row (quarantined ones included, read
                 from market_data_ohlcv_scrub_input) becomes a LEGACY_IMPORT observation
                 under one legacy request per symbol, so D1 holds the whole 1d history the
                 corpus was built on. Idempotent: a symbol that already has a LEGACY_IMPORT
                 request from this caller is skipped.
  fresh-fetch    IBKR, campaign client id 47. One fetch_run_id; for every 1d-eligible name
                 (MRNA and ALMS first), TRADES then ADJUSTED_LAST back from now for
                 infra.bar_campaign.bootstrap_years, so D5 can pair the series inside one
                 run. Both halves of a pair are flushed together and the lease is
                 checkpointed only after a full pair (D-22, D-29). Resumable with
                 --resume-run <fetch_run_id>: a symbol counts done only when both series
                 have a bars or no_data request in the run.

Every write after a long fetch opens a fresh connection (idle-session timeout, plan 13),
and progress is appended to a file as the run goes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg
import psycopg
import structlog

from scripts.ops.bars._campaign import CampaignRefused, preflight
from services.ohlcv_observation_writer import (
    AsyncObservationSink,
    ObservationSink,
    new_fetch_run_id,
)
from src.config.settings import Settings, get_active_contracts
from src.core.resource_lease import LeaseTimeout, ResourceLease, Tier
from src.providers.ibkr import HIST_RATE_LIMIT_KEYS, IBKRProvider, apply_hist_rate_limit_config

_logger = structlog.get_logger(__name__)

_CALLER = "d1-bootstrap"
_CLIENT_ID = 47
_LEASE_NAME = "ibkr_history_stream"
_LEGACY_ROUTE = "LEGACY_IMPORT"
_FIRST_NAMES = ("MRNA", "ALMS")
_SERIES = ("TRADES", "ADJUSTED_LAST")
_CLEAN = ("bars", "no_data")
_APR_YEARS = "infra.bar_campaign.bootstrap_years"
_APR_LEASE_WAIT = "infra.ibkr_history_lease.priority_wait_minutes"
_APR_BATCH_ROWS = "infra.ohlcv_observation.copy_batch_rows"
_PROGRESS_DIR = Path(__file__).resolve().parents[3] / "logs" / "d1_bootstrap"
_REFUSED_EXIT = 3
_INTERRUPTED_EXIT = 4


class LegacyBar(NamedTuple):
    """The bar shape the observation sink reads (duck-typed like an OHLCVBar)."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class LegacyRequest:
    """A RequestRecord-shaped legacy request (route LEGACY_IMPORT, outcome legacy_import)."""

    request_id: str
    fetch_run_id: str
    symbol: str
    timeframe: str
    route: str
    what_to_show: str
    primary_exchange: str | None
    window_start: datetime
    window_end: datetime
    ib_req_id: int | None
    outcome: str
    error_code: int | None
    error_text: str | None
    n_bars: int
    client_id: int | None
    requested_at: datetime
    answered_at: datetime


# --- pure pieces -----------------------------------------------------------------


def legacy_records(
    symbol: str,
    rows: Sequence[tuple[datetime, float, float, float, float, int]],
    *,
    fetch_run_id: str,
    now: datetime,
) -> tuple[LegacyRequest, list[LegacyBar]]:
    """One legacy request for a symbol's stored span and its bars (rows sorted by time)."""
    if not rows:
        raise ValueError(f"no stored rows for {symbol}; nothing to import")
    bars = [LegacyBar(*row) for row in rows]
    request = LegacyRequest(
        request_id=str(uuid.uuid4()),
        fetch_run_id=fetch_run_id,
        symbol=symbol,
        timeframe="1d",
        route=_LEGACY_ROUTE,
        what_to_show="TRADES",
        primary_exchange=None,
        window_start=bars[0].timestamp,
        window_end=bars[-1].timestamp,
        ib_req_id=None,
        outcome="legacy_import",
        error_code=None,
        error_text=None,
        n_bars=len(bars),
        client_id=None,
        requested_at=now,
        answered_at=now,
    )
    return request, bars


def order_symbols(symbols: Iterable[str]) -> list[str]:
    """MRNA and ALMS first (their verdict gates the report, D-24), the rest sorted."""
    unique = sorted(set(symbols))
    head = [s for s in _FIRST_NAMES if s in unique]
    return head + [s for s in unique if s not in head]


def symbols_done(outcomes: Mapping[str, Mapping[str, Sequence[str]]]) -> set[str]:
    """Symbols with a clean (bars or no_data) request for both series in the run.

    outcomes maps symbol -> what_to_show -> the outcomes of its requests in the run.
    """
    return {
        symbol
        for symbol, by_series in outcomes.items()
        if all(any(o in _CLEAN for o in by_series.get(series, ())) for series in _SERIES)
    }


def pending_symbols(all_symbols: Iterable[str], done: Iterable[str]) -> list[str]:
    done_set = set(done)
    return [s for s in order_symbols(all_symbols) if s not in done_set]


def _append_progress(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps({"at": datetime.now(UTC).isoformat(), **event}) + "\n")


# --- shared reads ----------------------------------------------------------------


def _load_apr(conn: Any) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state " "WHERE config_key LIKE ANY(%s)",
            (
                [
                    "infra.bar_campaign.%",
                    "infra.ibkr_history_lease.%",
                    "infra.ohlcv_observation.%",
                    "infra.ibkr.rate_limit%",
                ],
            ),
        )
        return {k: v for k, v in cur.fetchall()}


# --- legacy import ---------------------------------------------------------------


def _stored_symbols(conn: Any) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM market_data_ohlcv_scrub_input "
            "WHERE timeframe = '1d' AND source = 'ibkr_named' ORDER BY symbol"
        )
        return [row[0] for row in cur.fetchall()]


def _already_imported(conn: Any) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM ohlcv_request WHERE caller = %s AND route = %s",
            (_CALLER, _LEGACY_ROUTE),
        )
        return {row[0] for row in cur.fetchall()}


def _stored_rows(conn: Any, symbol: str) -> list[tuple[datetime, float, float, float, float, int]]:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "timestamp", open, high, low, close, volume '
            "FROM market_data_ohlcv_scrub_input "
            "WHERE symbol = %s AND timeframe = '1d' AND source = 'ibkr_named' "
            'ORDER BY "timestamp"',
            (symbol,),
        )
        return list(cur.fetchall())


def run_legacy_import(settings: Settings) -> int:
    fetch_run_id = new_fetch_run_id()
    read = psycopg.connect(settings.database_url, autocommit=True)
    write = psycopg.connect(settings.database_url, autocommit=True)
    try:
        apr = _load_apr(read)
        batch_rows = int(apr.get(_APR_BATCH_ROWS, 50_000))
        symbols = _stored_symbols(read)
        todo = [s for s in symbols if s not in _already_imported(read)]
        print(f"stored symbols: {len(symbols)}; to import: {len(todo)}; run {fetch_run_id}")
        # The sink's own auto-flush would split a symbol across transactions, so the
        # ceiling is set out of reach and whole symbols flush here.
        sink = ObservationSink(write, caller=_CALLER, max_buffer_rows=10**9)
        imported_rows = 0
        for i, symbol in enumerate(todo, 1):
            request, bars = legacy_records(
                symbol, _stored_rows(read, symbol), fetch_run_id=fetch_run_id, now=datetime.now(UTC)
            )
            sink.on_request(request)
            sink.on_observation(request, bars)
            imported_rows += len(bars)
            if sink.pending() >= batch_rows:
                sink.flush()
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} symbols, {imported_rows} rows buffered or written")
        sink.flush()
        print(f"legacy import done: {len(todo)} symbols, {imported_rows} observations")
    finally:
        read.close()
        write.close()
    return 0


# --- fresh fetch -----------------------------------------------------------------


def _eligible_instruments(settings: Settings) -> dict[str, Any]:
    return {i.symbol: i for i in get_active_contracts(settings, dimension="compute_1d")}


def _run_outcomes(conn: Any, run_id: str) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, what_to_show, outcome FROM ohlcv_request "
            "WHERE fetch_run_id = %s::uuid AND timeframe = '1d'",
            (run_id,),
        )
        for symbol, series, outcome in cur.fetchall():
            out.setdefault(symbol, {}).setdefault(series, []).append(outcome)
    return out


async def _flush_fresh(sink: AsyncObservationSink, dsn: str) -> tuple[int, int]:
    conn = await asyncpg.connect(dsn=dsn)
    try:
        return await sink.flush(conn)
    finally:
        await conn.close()


async def _fresh_fetch(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        apr = _load_apr(conn)
        try:
            preflight(client_id=_CLIENT_ID, apr=apr)
        except CampaignRefused as error:
            print(f"REFUSED: {error}")
            return _REFUSED_EXIT
        run_id = args.resume_run or new_fetch_run_id()
        instruments = _eligible_instruments(settings)
        done = symbols_done(_run_outcomes(conn, run_id)) if args.resume_run else set()
    todo = pending_symbols(instruments, done)
    if args.symbols:
        wanted = set(args.symbols)
        todo = [s for s in todo if s in wanted]
    years = int(apr.get(_APR_YEARS, 20))
    progress = _PROGRESS_DIR / f"{run_id}.jsonl"
    print(
        f"fetch_run_id: {run_id}; eligible {len(instruments)}; done {len(done)}; todo {len(todo)}"
    )
    _append_progress(progress, {"event": "start", "todo": len(todo), "done": len(done)})
    apply_hist_rate_limit_config({k: apr[k] for k in HIST_RATE_LIMIT_KEYS if k in apr})

    lease = ResourceLease(
        settings.database_url,
        _LEASE_NAME,
        tier=Tier.PRIORITY,
        holder=f"{_CALLER}:{_CLIENT_ID}",
    )
    try:
        lease.acquire(float(apr.get(_APR_LEASE_WAIT, 240)) * 60.0)
    except LeaseTimeout:
        lease.close()
        print("lease timeout: nothing fetched; rerun with --resume-run", run_id)
        return _INTERRUPTED_EXIT

    sink = AsyncObservationSink(
        caller=_CALLER, max_buffer_rows=int(apr.get(_APR_BATCH_ROWS, 50_000))
    )
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=_CLIENT_ID)
    exit_code = 0
    consecutive = 0
    try:
        if not await provider.connect():
            print("cannot connect to IBKR gateway; rerun with --resume-run", run_id)
            return _INTERRUPTED_EXIT
        for n, symbol in enumerate(todo, 1):
            if not await provider.qualify_instrument(instruments[symbol]):
                _append_progress(progress, {"event": "qualify_failed", "symbol": symbol})
                consecutive += 1
            else:
                errors: dict[str, str | None] = {}
                for series in _SERIES:
                    _, errors[series] = await provider.fetch_adjusted_daily_closes(
                        symbol,
                        years,
                        on_request=sink.on_request,
                        on_observation=sink.on_observation,
                        fetch_run_id=run_id,
                        what_to_show=series,
                    )
                # Both halves flush together, then the lease checkpoint (D-22, D-29).
                await _flush_fresh(sink, dsn)
                lease.checkpoint()
                hard = {s: e for s, e in errors.items() if e and "returned no bars" not in e}
                _append_progress(progress, {"event": "pair", "symbol": symbol, "errors": errors})
                consecutive = consecutive + 1 if hard else 0
            if n % 25 == 0:
                print(f"  {n}/{len(todo)} names")
            if consecutive >= args.max_consecutive_failures:
                print(
                    f"{consecutive} consecutive failures: stopping; rerun with --resume-run {run_id}"
                )
                exit_code = _INTERRUPTED_EXIT
                break
    except Exception as error:
        # A dropped gateway connection (nightly 23:59 UTC restart) lands here; the buffered
        # half-pair is discarded on purpose and the symbol is re-fetched on resume.
        print(f"interrupted: {type(error).__name__}: {error}; rerun with --resume-run {run_id}")
        _append_progress(progress, {"event": "interrupted", "error": str(error)})
        exit_code = _INTERRUPTED_EXIT
    finally:
        try:
            await provider.disconnect()
        finally:
            lease.release()
            lease.close()
    _append_progress(progress, {"event": "end", "exit": exit_code})
    return exit_code


# --- main ------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("legacy-import", help="stored ibkr_named 1d rows into D1 (no IBKR)")
    fresh = sub.add_parser("fresh-fetch", help="paired TRADES and ADJUSTED_LAST fetch")
    fresh.add_argument("--resume-run", default=None, help="fetch_run_id of an earlier run")
    fresh.add_argument("--symbols", nargs="*", default=None, help="limit to these names")
    fresh.add_argument("--max-consecutive-failures", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "legacy-import":
        sys.exit(run_legacy_import(Settings()))
    sys.exit(asyncio.run(_fresh_fetch(args)))


if __name__ == "__main__":
    main()
