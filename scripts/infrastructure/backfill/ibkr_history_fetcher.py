#!/usr/bin/env python3
"""ibkr_history_fetcher.py -- the single IBKR history fetcher (phase 189 plan 04).

Design: docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md. One process owns
the IBKR history connection (CD-01), works a priority queue over the ohlcv_coverage ledger one
(symbol, timeframe) at a time (CD-06), records every outcome in the ledger (CD-03/CD-05), and
promotes the derived grid in the same pass (CD-07). It absorbs
infrastructure_run_historical_pipeline.py's CLI (same flag names and meanings where they
exist) and the run-level stages of infrastructure_nightly_backfill.py (split detection, the
daily and grid derivation stages, the D7 run status file), so plan 189-07 can delete both.

Flow (CD-01/CD-02/CD-07):

    FetcherLock.acquire()                  -- fail fast: held elsewhere -> exit 0, lock_held
      -> resolve scopes -> candidates      -- APR infra.backfill.default_scopes union, deduped;
                                              Tradier-owned 1d series skipped (185 D2 rule)
      -> IBKRProvider.connect()            -- unreachable -> raise, status failure (CD-08)
      -> loop until budget or queue empty:
           row = queue.next(pool, visited) -- reads ohlcv_coverage, pure ranking
           fetch_item_with_retries(...)    -- stall-bounded, atomic chunk + coverage writes
           record_fetch_outcome(...)       -- one ledger write per item (not on gateway loss)
      -> disconnect; final D1 sink flush
      -> split detection (185-22) -> daily stage + 1d ledger refresh -> grid stage
      -> SLA gauge, status file, run summary
    FetcherLock.release()

Statuses (job_completed_total{job="ibkr-history-fetcher"}): success (every item ok or
no_data, every stage clean), partial (an item ended error or a stage failed; recorded in the
ledger, exit 0, not a failed unit), lock_held (another holder; exit 0), dry_run, failure
(gateway unreachable at startup or lost mid-run, or any unexpected error; exit 1). The
recurring systemd timer is the retry; there is no polling loop.

A wedged event loop is killed from outside: the unit runs Type=exec with WatchdogSec and
RuntimeMaxSec, and this process pings WATCHDOG=1 only from its live loop (per item, on every
stall check inside an item, and while awaiting a stage subprocess).

The D7 reconciliation audit (services/bar_reconciliation_audit.py) is not run from here: the
nightly ran it once a day as its last step, and this fetcher fires every 15 minutes. The
fetcher writes the run status file the audit's nightly_skipped check reads; the audit gets
its own daily caller at cutover (plan 189-06/07). The Tradier daily load
(infrastructure_run_tradier_daily.py) stays its own script with its own caller.

Exit codes: 0 for success, partial, lock_held, dry_run; 1 when run() raises.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill import _empty_history as empty_history  # noqa: E402
from scripts.infrastructure.backfill import (  # noqa: E402
    infrastructure_run_historical_pipeline as _pipeline,
)
from scripts.infrastructure.backfill._fetch_queue import (  # noqa: E402
    PriorityQueue,
    QueueConfig,
    RankedItem,
    load_queue_config,
)
from scripts.infrastructure.backfill._fetcher_lock import (  # noqa: E402
    FETCHER_LOCK_NAME,
    LOCK_HELD_MESSAGE,
    FetcherLock,
)
from scripts.infrastructure.backfill._history_fetch_item import (  # noqa: E402
    FetchContext,
    ItemOutcome,
    fetch_item_with_retries,
)

# The Tradier-owned predicate is D2's own probe (commit 2811eb044, "one source per name"),
# imported rather than copied so the fetcher and the daily stage can never disagree.
from services.bar_derivation import (  # noqa: E402
    _SELECT_DAILY_CHANGED_SINCE_SQL as _DAILY_SOURCE_PROBE_SQL,
)
from services.bar_reconciliation_audit import NIGHTLY_STATUS_FILE  # noqa: E402
from services.ohlcv_coverage_writer import (  # noqa: E402
    rebuild_from_stored_state,
    record_fetch_outcome,
    refresh_1d_bounds,
    reset_failures,
)
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id  # noqa: E402
from src.config.settings import (  # noqa: E402
    Settings,
    get_active_contracts,
    get_all_futures_contracts,
)
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402
from src.observability.metrics import OHLCV_COVERAGE_SLA_BREACHED_SERIES  # noqa: E402
from src.providers import IBKRProvider  # noqa: E402

logger = structlog.get_logger(__name__)

JOB = "ibkr-history-fetcher"
_OBSERVATION_CALLER = JOB
_WRITER_ROLE = "bar_derivation_writer"
_DIMENSIONS = ("backfill", "compute", "compute_1d", "live")
_DERIVATION_SCRIPT = project_root / "services" / "bar_derivation.py"
_SPLIT_DETECT_SCRIPT = project_root / "scripts" / "ops" / "bars" / "ops_split_detect.py"
_DAILY_TF = "1d"

# APR keys read once at startup. Missing keys raise: the migrations seed them (406, 432).
_KEY_OVERLAP_SESSIONS = "infra.bar_derivation.overlap_sessions"
_KEY_INTER_ITEM_PAUSE = "infra.ibkr.inter_item_pause_s"

# Calendar slack for finding the latest completed NYSE session: longer than any market
# closure on record, so the window always holds one close. A calendar fact, not a tunable.
_SESSION_LOOKBACK_DAYS = 14
# Liveness pings while awaiting a stage subprocess run at the item stall check's cadence
# (history_request_timeout / 3), so one WatchdogSec bound covers both.
_TICKS_PER_TIMEOUT = 3
_DRY_RUN_PRINT_ROWS = 40

_TSV_COLUMNS = (
    "position",
    "symbol",
    "timeframe",
    "excluded",
    "sla_breach",
    "tf_class",
    "gap_days",
    "staleness_days",
    "earliest_timestamp",
    "latest_timestamp",
    "last_fetch_status",
    "consecutive_failures",
    "last_fetched_at",
    "held_reason",
)


# ---------------------------------------------------------------------------
# CLI and scope resolution (pure)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Single IBKR history fetcher (phase 189): ledger-ranked, lock-guarded."
    )
    parser.add_argument(
        "--dimension",
        default=None,
        choices=_DIMENSIONS,
        help=(
            "get_active_contracts() dimension. With neither --dimension nor --timeframes the "
            "fetcher queues the APR infra.backfill.default_scopes union. backfill and "
            "compute_1d require an explicit --timeframes."
        ),
    )
    parser.add_argument(
        "--timeframes",
        default=None,
        help=(
            "Comma-separated timeframes for --dimension (default: that dimension's "
            "default_scopes entry). Alone, it applies to --dimension compute."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated contract or base symbols restricting the resolved scope.",
    )
    parser.add_argument(
        "--days", type=int, default=None, help="Cap every timeframe's fetch depth (days)."
    )
    parser.add_argument("--client-id", type=int, default=40, help="IBKR client ID (default 40)")
    parser.add_argument(
        "--include-rolled",
        action="store_true",
        help="Include rolled/expired futures contracts, not only the front month.",
    )
    parser.add_argument(
        "--per-contract", action="store_true", help="Per-contract futures fetch (raw, unadjusted)."
    )
    parser.add_argument(
        "--seed-roll-chain",
        action="store_true",
        help="Populate contract_metadata roll chains (under the lock, no IBKR) and exit.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Fill gaps in stored rows with synthetic flat bars (under the lock, no IBKR).",
    )
    parser.add_argument(
        "--budget-minutes",
        type=float,
        default=None,
        help="Stop taking new items after this long (default APR "
        "infra.backfill.run_budget_minutes).",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Plan every item over its full depth window, not from its latest bar.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print and write the ranked queue; no lock, no IBKR connection, no writes.",
    )
    parser.add_argument(
        "--dry-run-out",
        default=None,
        help="TSV path for --dry-run (default logs/ibkr_history_fetcher_dryrun_<UTC>.tsv).",
    )
    parser.add_argument(
        "--reset-failures",
        default=None,
        metavar="SYMBOL[:TF]",
        help="Zero consecutive_failures through the ledger writer and exit.",
    )
    parser.add_argument(
        "--rebuild-coverage",
        action="store_true",
        help=(
            "Recompute every ohlcv_coverage row's bounds and row count from the stored bars "
            "(under the lock, no IBKR) and exit. For a ledger another writer bypassed."
        ),
    )
    return parser


def validate_args(args: argparse.Namespace) -> str | None:
    """The pipeline's explicit-timeframes rule; returns an error message or None."""
    if args.dimension in ("backfill", "compute_1d") and args.timeframes is None:
        return (
            f"--dimension {args.dimension} requires an explicit --timeframes: it includes "
            "symbols deliberately kept off the full timeframe stack (e.g. the 1d-only cohort)."
        )
    return None


def _split_csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def resolve_scopes(
    args: argparse.Namespace, default_scopes: Mapping[str, Sequence[str]]
) -> list[tuple[str, tuple[str, ...]]]:
    """(dimension, timeframes) scopes this run queues.

    No --dimension and no --timeframes: the default_scopes union (--symbols then narrows
    it). Otherwise one scope: --dimension (default compute) at --timeframes, or at that
    dimension's default_scopes entry. Raises ValueError when no timeframes resolve.
    """
    if args.dimension is None and args.timeframes is None:
        return [(dim, tuple(tfs)) for dim, tfs in default_scopes.items()]
    dimension = args.dimension or "compute"
    if args.timeframes is not None:
        timeframes = tuple(_split_csv(args.timeframes))
    else:
        timeframes = tuple(default_scopes.get(dimension, ()))
    if not timeframes:
        raise ValueError(f"no timeframes for --dimension {dimension}; pass --timeframes")
    return [(dimension, timeframes)]


def _symbol_matches(symbol: str, wanted: set[str]) -> bool:
    base = (_pipeline._parse_contract_symbol(symbol) or (None,))[0]
    return symbol in wanted or base in wanted


@dataclass
class Candidates:
    """The resolved (symbol, timeframe) pairs and the instrument behind each symbol."""

    pairs: list[tuple[str, str]]
    instruments: dict[str, Any]
    scope_contracts: list[tuple[tuple[str, ...], list[Any]]] = field(default_factory=list)
    unknown_timeframes: list[str] = field(default_factory=list)


def build_candidates(
    scopes: Sequence[tuple[str, Sequence[str]]],
    contracts_for: Callable[[str], list[Any]],
    *,
    symbols: Iterable[str] = (),
    fetchable_timeframes: Iterable[str] | None = None,
) -> Candidates:
    """Deduplicated (symbol, timeframe) pairs over every scope, in scope order.

    A symbol in two scopes keeps the instrument of the first. Timeframes outside
    `fetchable_timeframes` (the per-timeframe fetch config) are dropped and reported.
    """
    wanted = set(symbols)
    fetchable = None if fetchable_timeframes is None else set(fetchable_timeframes)
    pairs: dict[tuple[str, str], None] = {}
    instruments: dict[str, Any] = {}
    scope_contracts: list[tuple[tuple[str, ...], list[Any]]] = []
    unknown: set[str] = set()
    for dimension, timeframes in scopes:
        contracts = contracts_for(dimension)
        if wanted:
            contracts = [c for c in contracts if _symbol_matches(c.symbol, wanted)]
        tfs = []
        for tf in timeframes:
            if fetchable is not None and tf not in fetchable:
                unknown.add(tf)
            else:
                tfs.append(tf)
        scope_contracts.append((tuple(tfs), contracts))
        for contract in contracts:
            instruments.setdefault(contract.symbol, contract)
            for tf in tfs:
                pairs.setdefault((contract.symbol, tf), None)
    return Candidates(list(pairs), instruments, scope_contracts, sorted(unknown))


def last_session_close(now: datetime) -> datetime | None:
    """The latest NYSE session close at or before `now` (UTC), or None.

    One calendar for every candidate: today's universe is all NYSE-session equity, and the
    1d planner refuses any other calendar the same way (asset_agnostic caveat, as there).
    """
    sessions = nyse_sessions(now.date() - timedelta(days=_SESSION_LOOKBACK_DAYS), now.date())
    closes = [close for _open, close in sessions.values() if close <= now]
    return max(closes) if closes else None


def parse_reset_target(value: str) -> tuple[str, str | None]:
    symbol, _, timeframe = value.partition(":")
    if not symbol.strip():
        raise ValueError(f"--reset-failures needs SYMBOL[:TF], got {value!r}")
    return symbol.strip(), (timeframe.strip() or None)


# ---------------------------------------------------------------------------
# Run plan
# ---------------------------------------------------------------------------


@dataclass
class RunPlan:
    """Everything a run (or a dry run) needs before it touches IBKR. Built from reads only."""

    config: QueueConfig
    queue: Any  # PriorityQueue: load(pool), next(pool, visited), ranked/held snapshots
    candidates: Candidates
    tradier_owned: list[tuple[str, str]]
    tf_fetch_config: Mapping[str, tuple[int, bool]]
    overlap_sessions: int
    inter_item_pause_s: float


def _read_apr(conn: Any, keys: Sequence[str]) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            (list(keys),),
        )
        values = {str(k): str(v) for k, v in cur.fetchall()}
    missing = sorted(set(keys) - set(values))
    if missing:
        raise RuntimeError(f"APR keys not set: {missing}")
    return values


def _default_contracts_for(settings: Settings, include_rolled: bool) -> Callable[[str], list[Any]]:
    """The pipeline's contract selection per dimension (futures + --include-rolled as today)."""

    def contracts_for(dimension: str) -> list[Any]:
        active = get_active_contracts(settings, dimension=dimension)
        if not include_rolled:
            return active
        futures = get_all_futures_contracts(settings)
        futures_symbols = {c.symbol for c in futures}
        return futures + [c for c in active if c.symbol not in futures_symbols]

    return contracts_for


# ---------------------------------------------------------------------------
# The fetcher
# ---------------------------------------------------------------------------


def _sd_notify_watchdog() -> None:
    """WATCHDOG=1 to systemd; a no-op outside a unit (no NOTIFY_SOCKET)."""
    if not os.getenv("NOTIFY_SOCKET"):
        return
    import sdnotify  # type: ignore[import-untyped]

    sdnotify.SystemdNotifier().notify("WATCHDOG=1")


class IbkrHistoryFetcher(BaseBatch):
    """The single IBKR history fetcher oneshot (CD-01/CD-02/CD-07).

    Constructor seams exist for tests and replace exactly one dependency each: the provider
    factory (IBKRProvider), the lock name or the whole lock, the item fetch (fetch_item_with_retries), the run
    plan (reads), the stage runner (subprocess), the psycopg connect, the contract source,
    the watchdog notifier, and the status file path.
    """

    job_name = JOB
    compute_version = "189.1"

    def __init__(
        self,
        db_dsn: str,
        args: argparse.Namespace,
        *,
        settings: Settings | None = None,
        provider_factory: Callable[[], Any] | None = None,
        lock_name: str = FETCHER_LOCK_NAME,
        lock_factory: Callable[[], Any] | None = None,
        fetch_fn: Callable[..., Awaitable[ItemOutcome]] = fetch_item_with_retries,
        prepare: Callable[[Any], Awaitable[RunPlan]] | None = None,
        context_factory: Callable[[Any, RunPlan, str], Any] | None = None,
        stage_runner: Callable[[list[str]], Awaitable[int]] | None = None,
        connect: Callable[[], Any] | None = None,
        contracts_for: Callable[[str], list[Any]] | None = None,
        notify: Callable[[], None] = _sd_notify_watchdog,
        status_file: Path = NIGHTLY_STATUS_FILE,
    ) -> None:
        super().__init__(db_dsn)
        self.args = args
        self.settings = settings or Settings()
        self._provider_factory = provider_factory or self._default_provider
        self._lock_name = lock_name
        self._lock_factory = lock_factory or (
            lambda: FetcherLock(
                self.settings.database_url,
                holder=f"{JOB}:{self.args.client_id}",
                name=self._lock_name,
            )
        )
        self._fetch_fn = fetch_fn
        self._prepare = prepare or self.prepare
        self._context_factory = context_factory or self._default_context
        self._run_stage = stage_runner or self._run_subprocess
        self._connect = connect or (lambda: _pipeline.connect_db(self.settings))
        self._contracts_for = contracts_for or _default_contracts_for(
            self.settings, args.include_rolled
        )
        self._notify = notify
        self._status_file = status_file
        self._tick_s: float | None = None
        self.summary: dict[str, Any] = {}

    # -- seams' defaults ----------------------------------------------------

    def _default_provider(self) -> Any:
        return IBKRProvider(
            host=self.settings.ib_host, port=self.settings.ib_port, client_id=self.args.client_id
        )

    def _default_context(self, provider: Any, plan: RunPlan, fetch_run_id: str) -> FetchContext:
        conn = self._connect()
        try:
            empty_ranges = empty_history.load(conn, _pipeline._EMPTY_HISTORY_PROVIDER)
            reverify_days = empty_history.load_reverify_days(conn)
            fresh_heads = empty_history.load_fresh_heads(
                conn, _pipeline._EMPTY_HISTORY_PROVIDER, reverify_days
            )
            first_bars = empty_history.load_first_bars(conn, list(plan.candidates.instruments))
        finally:
            conn.close()
        sink = ObservationSink(
            self._connect(),
            caller=_OBSERVATION_CALLER,
            max_buffer_rows=_pipeline._load_observation_batch_rows(self.settings),
        )
        now = datetime.now(UTC)
        return FetchContext(
            provider=provider,
            settings=self.settings,
            connect=self._connect,
            sink=sink,
            fetch_run_id=fetch_run_id,
            tf_fetch_config=plan.tf_fetch_config,
            end_dt=now,
            run_started_at=now,
            empty_ranges=empty_ranges,
            empty_reverify_days=reverify_days,
            fresh_heads=fresh_heads,
            first_bars=first_bars,
            days_override=self.args.days,
            per_contract=self.args.per_contract,
            overlap_sessions=plan.overlap_sessions,
        )

    async def _run_subprocess(self, argv: list[str]) -> int:
        """A stage subprocess, awaited without blocking the loop so watchdog pings continue."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(project_root),
            env={**os.environ, "PYTHONPATH": str(project_root)},
        )
        while True:
            try:
                return await asyncio.wait_for(proc.wait(), timeout=self._tick_s)
            except TimeoutError:
                self._notify()

    # -- reads ----------------------------------------------------------------

    async def prepare(self, pool: Any) -> RunPlan:
        """Resolve scopes, candidates and the queue. Reads only: shared by the dry run."""
        conn = self._connect()
        try:
            config = load_queue_config(conn)
            apr = _read_apr(conn, (_KEY_OVERLAP_SESSIONS, _KEY_INTER_ITEM_PAUSE))
        finally:
            conn.close()
        tf_fetch_config = _pipeline._load_tf_fetch_config(self.settings)
        scopes = resolve_scopes(self.args, config.default_scopes)
        candidates = build_candidates(
            scopes,
            self._contracts_for,
            symbols=_split_csv(self.args.symbols),
            fetchable_timeframes=tf_fetch_config,
        )
        if candidates.unknown_timeframes:
            logger.warning(
                "ibkr_history_fetcher.unknown_timeframes_dropped",
                timeframes=candidates.unknown_timeframes,
            )
        owned = await self._tradier_owned(pool, {s for s, tf in candidates.pairs if tf == "1d"})
        tradier_owned = [(s, tf) for s, tf in candidates.pairs if tf == _DAILY_TF and s in owned]
        skipped = set(tradier_owned)
        fetchable = [pair for pair in candidates.pairs if pair not in skipped]
        now = datetime.now(UTC)
        queue = PriorityQueue(config, fetchable, now.date(), current_after=last_session_close(now))
        await queue.load(pool)
        return RunPlan(
            config=config,
            queue=queue,
            candidates=candidates,
            tradier_owned=tradier_owned,
            tf_fetch_config=tf_fetch_config,
            overlap_sessions=int(float(apr[_KEY_OVERLAP_SESSIONS])),
            inter_item_pause_s=float(apr[_KEY_INTER_ITEM_PAUSE]),
        )

    @staticmethod
    async def _tradier_owned(pool: Any, symbols: Iterable[str]) -> set[str]:
        """1d symbols whose latest daily load came from Tradier (D2's probe, one per name)."""
        owned: set[str] = set()
        async with pool.acquire() as conn:
            for symbol in sorted(symbols):
                probe = await conn.fetchrow(_DAILY_SOURCE_PROBE_SQL, symbol)
                if probe is not None and probe["tradier_owned"]:
                    owned.add(symbol)
        return owned

    # -- entry ----------------------------------------------------------------

    async def execute(self, pool: Any) -> None:
        if self.args.reset_failures:
            self._reset_failures(self.args.reset_failures)
            return
        if self.args.dry_run:
            await self._dry_run(pool)
            self.completion_status = "dry_run"
            return
        lock = self._lock_factory()
        if not lock.acquire():
            print(LOCK_HELD_MESSAGE)
            logger.info("ibkr_history_fetcher.lock_held", lock=self._lock_name)
            self.completion_status = "lock_held"
            return
        try:
            if self.args.rebuild_coverage:
                self._rebuild_coverage()
            else:
                await self._locked_run(pool)
        finally:
            lock.close()

    def _rebuild_coverage(self) -> None:
        """Recompute the ledger from stored state under the lock, so no fetch interleaves."""
        conn = self._connect()
        try:
            with conn.transaction():
                cur = conn.cursor()
                cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
                n_rows = rebuild_from_stored_state(cur)
        finally:
            conn.close()
        print(f"rebuilt {n_rows} ohlcv_coverage row(s) from stored state")
        logger.info("ibkr_history_fetcher.coverage_rebuilt", n_rows=n_rows)

    def _reset_failures(self, target: str) -> None:
        symbol, timeframe = parse_reset_target(target)
        conn = self._connect()
        try:
            with conn.transaction():
                cur = conn.cursor()
                cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
                n_rows = reset_failures(cur, symbol, timeframe)
        finally:
            conn.close()
        print(f"reset consecutive_failures on {n_rows} ledger row(s) for {target}")
        logger.info(
            "ibkr_history_fetcher.failures_reset",
            symbol=symbol,
            timeframe=timeframe,
            n_rows=n_rows,
        )

    # -- dry run ----------------------------------------------------------------

    async def _dry_run(self, pool: Any) -> None:
        plan = await self._prepare(pool)
        rows = dry_run_rows(plan)
        out = Path(
            self.args.dry_run_out
            or project_root
            / "logs"
            / f"ibkr_history_fetcher_dryrun_{datetime.now(UTC):%Y%m%dT%H%M%S}.tsv"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(_TSV_COLUMNS)
            writer.writerows(rows)
        for row in rows[:_DRY_RUN_PRINT_ROWS]:
            print("\t".join(row))
        bands = Counter(
            f"sla_breach={r[4]} tf_class={r[5]}" if r[13] == "" else f"held={r[13]}" for r in rows
        )
        print(f"\n{len(rows)} candidate series -> {out}")
        for band, n in sorted(bands.items()):
            print(f"  {band}: {n}")
        logger.info("ibkr_history_fetcher.dry_run", n_series=len(rows), out=str(out), **bands)

    # -- the locked run --------------------------------------------------------------

    async def _locked_run(self, pool: Any) -> None:
        started_at = datetime.now(UTC)
        try:
            await self._fetch_and_promote(pool)
        except Exception as error:
            self._write_status("failed", started_at, f"{type(error).__name__}: {error}")
            raise
        status = self.completion_status or "success"
        self._write_status(status, started_at, json.dumps(self.summary, default=str))

    async def _fetch_and_promote(self, pool: Any) -> None:
        if self.args.seed_roll_chain:
            await self._seed_roll_chain()
            return
        plan = await self._prepare(pool)
        self._tick_s = plan.config.history_request_timeout_s / _TICKS_PER_TIMEOUT
        if self.args.normalize:
            self._normalize(plan)
            return
        self._load_provider_overlays()
        fetch_run_id = new_fetch_run_id()
        # Exact format the pipeline printed: ops_head_rerun parses it.
        print(f"  fetch_run_id: {fetch_run_id}")

        provider = self._provider_factory()
        self._notify()
        if not await provider.connect():
            raise RuntimeError("IBKR gateway unreachable at startup")
        ctx: Any = None
        try:
            ctx = self._context_factory(provider, plan, fetch_run_id)
            loop = await self._loop(pool, plan, ctx, provider)
        finally:
            try:
                await provider.disconnect()
            except Exception as error:  # a dead socket may refuse a clean disconnect
                logger.warning("ibkr_history_fetcher.disconnect_failed", error=str(error))
            if ctx is not None:
                self._final_flush(ctx)
        stage_codes = await self._run_end_stages(ctx, loop, fetch_run_id)
        sla_breached = await self._sla_breached(pool, plan)
        self.summary = {
            "fetch_run_id": fetch_run_id,
            **loop.counts(),
            "budget_exhausted": loop.budget_exhausted,
            "gateway_lost": loop.gateway_lost,
            "sla_breached": sla_breached,
            "stages": stage_codes,
        }
        logger.info("ibkr_history_fetcher.run_summary", **self.summary)
        print(f"run summary: {json.dumps(self.summary, default=str)}")
        if loop.gateway_lost:
            raise RuntimeError(f"IBKR gateway lost mid-run at {loop.gateway_lost}")
        failed = loop.n_error > 0 or any(rc != 0 for rc in stage_codes.values())
        self.completion_status = "partial" if failed else "success"

    async def _loop(self, pool: Any, plan: RunPlan, ctx: Any, provider: Any) -> _LoopState:
        budget_min = (
            self.args.budget_minutes
            if self.args.budget_minutes is not None
            else plan.config.run_budget_minutes
        )
        deadline = time.monotonic() + budget_min * 60
        state = _LoopState()
        visited: set[tuple[str, str]] = set()
        while True:
            if time.monotonic() >= deadline:
                state.budget_exhausted = True
                break
            row = await plan.queue.next(pool, visited)
            if row is None:
                break
            key = (row.symbol, row.timeframe)
            if key in visited:  # the queue handed back a visited item: never fetch twice
                logger.error("ibkr_history_fetcher.queue_repeated_item", symbol=key[0], tf=key[1])
                break
            visited.add(key)
            outcome = await self._fetch_fn(
                ctx,
                plan.candidates.instruments[row.symbol],
                row,
                gap_days=_gap_days(plan.queue, key),
                full_scan=self.args.full_scan,
                config=plan.config,
                reconnect=provider.connect,
                on_tick=self._notify,
            )
            self._notify()
            if outcome.gateway_lost:
                # The gateway, not the item, failed: nothing is charged to the series (CD-05).
                state.gateway_lost = f"{row.symbol}/{row.timeframe}"
                break
            self._record_outcome(ctx, outcome)
            state.add(outcome)
            await asyncio.sleep(plan.inter_item_pause_s)
        return state

    def _record_outcome(self, ctx: Any, outcome: ItemOutcome) -> None:
        conn = ctx.get_conn()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            record_fetch_outcome(
                cur, outcome.symbol, outcome.timeframe, outcome.status, datetime.now(UTC)
            )

    def _final_flush(self, ctx: Any) -> None:
        """The pipeline's best-effort final D1 flush: an item that died mid-fetch may have left
        buffered answers. Never masks the primary outcome."""
        try:
            if ctx.sink.pending():
                _pipeline._flush_capture(ctx.sink, self.settings)
        except Exception as error:  # noqa: BLE001
            logger.error("ibkr_history_fetcher.final_flush_failed", error=str(error))

    async def _run_end_stages(self, ctx: Any, loop: _LoopState, fetch_run_id: str) -> dict:
        """Split detection, the daily stage and its ledger refresh, the grid stage.

        Order as the nightly's: splits are judged first so the daily stage derives a split
        symbol's history on one scale (185-22); the daily stage runs before the grid stage
        so the two derivation writers never overlap. Under the lock no other IBKR writer
        exists, so no lane-guard exclude file is needed.
        """
        codes: dict[str, int] = {}
        python = sys.executable
        if loop.touched_1d:
            codes["split_detect"] = await self._run_stage(
                [
                    python,
                    str(_SPLIT_DETECT_SCRIPT),
                    "--client-id",
                    str(self.args.client_id),
                    "--fetch-run-id",
                    fetch_run_id,
                ]
            )
            symbols = sorted(loop.touched_1d)
            codes["daily"] = await self._run_stage(
                [
                    python,
                    str(_DERIVATION_SCRIPT),
                    "--stage",
                    "daily",
                    "--symbols",
                    ",".join(symbols),
                    "--apply",
                ]
            )
            if codes["daily"] == 0:
                self._finish_1d(ctx, loop.touched_1d)
        if loop.n_grid_source_rows > 0:
            codes["grid"] = await self._run_stage(
                [python, str(_DERIVATION_SCRIPT), "--stage", "grid", "--changed-only", "--apply"]
            )
        return codes

    def _finish_1d(self, ctx: Any, touched: Mapping[str, datetime]) -> None:
        """Refresh the 1d ledger bounds from D2's rows, then mark 1d fetch_complete (the
        pipeline's post-stage step; the EXISTS guard reads the rows the stage wrote)."""
        conn = ctx.get_conn()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            refresh_1d_bounds(cur, touched)
        for symbol, since in sorted(touched.items()):
            _pipeline.mark_fetch_complete(conn, symbol, _DAILY_TF, since)

    async def _sla_breached(self, pool: Any, plan: RunPlan) -> int:
        await plan.queue.load(pool)
        n = sum(1 for item in _all_items(plan.queue) if item.sla_breach)
        OHLCV_COVERAGE_SLA_BREACHED_SERIES.set(n, {"job": JOB})
        return n

    # -- non-IBKR modes and helpers ----------------------------------------------

    async def _seed_roll_chain(self) -> None:
        from src.core.database_manager import DatabaseManager

        db = DatabaseManager(self.settings.database_url)
        await db.initialize()
        try:
            await _pipeline.seed_roll_chain(self.settings, db)
        finally:
            await db.close()

    def _normalize(self, plan: RunPlan) -> None:
        conn = self._connect()
        try:
            for timeframes, contracts in plan.candidates.scope_contracts:
                _pipeline.run_normalize(conn, contracts, list(timeframes))
        finally:
            conn.close()

    def _load_provider_overlays(self) -> None:
        """The pipeline's APR overlays, in its main()'s order (module globals of ibkr.py and
        the pipeline that fetch_item reads)."""
        settings = self.settings
        _pipeline._load_ibkr_chunk_days_config(settings)
        _pipeline._load_ibkr_hist_timeout_config(settings)
        _pipeline._load_ibkr_retry_config(settings)
        _pipeline._load_ibkr_venue_fallback_config(settings)
        _pipeline._load_ibkr_rate_limit_config(settings)
        _pipeline._load_ohlcv_insert_batch_size_config(settings)
        _pipeline._load_gap_cluster_max_days_config(settings)

    def _write_status(self, status: str, started_at: datetime, message: str) -> None:
        """The run status file the D7 audit's nightly_skipped check reads (185-23). Written at
        the end of every locked run (not for lock_held or dry runs). Never raises."""
        payload: dict[str, Any] = {
            "status": status,
            "job": JOB,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "returncode": 0 if status in ("success", "partial") else 1,
            "lease_timeout_legs": [],
            "message": message,
        }
        try:
            self._status_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._status_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, default=str))
            tmp.replace(self._status_file)
        except OSError as error:
            logger.warning("ibkr_history_fetcher.status_file_write_failed", error=str(error))


@dataclass
class _LoopState:
    n_ok: int = 0
    n_no_data: int = 0
    n_error: int = 0
    n_bars: int = 0
    n_grid_source_rows: int = 0
    budget_exhausted: bool = False
    gateway_lost: str | None = None
    touched_1d: dict[str, datetime] = field(default_factory=dict)

    def add(self, outcome: ItemOutcome) -> None:
        if outcome.status == "ok":
            self.n_ok += 1
        elif outcome.status == "no_data":
            self.n_no_data += 1
        else:
            self.n_error += 1
        self.n_bars += outcome.n_bars
        self.n_grid_source_rows += outcome.n_grid_source_rows
        # Only a clean 1d item is derived and marked complete (189-03 interface).
        if outcome.derive_1d_since is not None and outcome.status == "ok":
            self.touched_1d[outcome.symbol] = outcome.derive_1d_since

    def counts(self) -> dict[str, int]:
        return {
            "n_items": self.n_ok + self.n_no_data + self.n_error,
            "n_ok": self.n_ok,
            "n_no_data": self.n_no_data,
            "n_error": self.n_error,
            "n_bars": self.n_bars,
            "n_grid_source_rows": self.n_grid_source_rows,
            "n_1d_derived": len(self.touched_1d),
        }


def _all_items(queue: Any) -> list[RankedItem]:
    return list(queue.ranked_snapshot()) + [item for item, _ in queue.held_snapshot()]


def _gap_days(queue: Any, key: tuple[str, str]) -> int:
    for item in queue.ranked_snapshot():
        if (item.row.symbol, item.row.timeframe) == key:
            return int(item.gap_days)
    raise RuntimeError(f"queue returned {key} but its ranked snapshot does not hold it")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def dry_run_rows(plan: RunPlan) -> list[list[str]]:
    """TSV rows: the queue in order (position 1..n), then held series, then Tradier-owned."""
    rows: list[list[str]] = []

    def add(position: str, item: RankedItem, reason: str) -> None:
        r = item.row
        rows.append(
            [
                position,
                r.symbol,
                r.timeframe,
                str(reason == "excluded"),
                str(item.sla_breach),
                str(item.tf_class),
                str(item.gap_days),
                _fmt(item.staleness_days),
                _fmt(r.earliest_timestamp),
                _fmt(r.latest_timestamp),
                _fmt(r.last_fetch_status),
                str(r.consecutive_failures),
                _fmt(r.last_fetched_at),
                reason,
            ]
        )

    for position, item in enumerate(plan.queue.ranked_snapshot(), start=1):
        add(str(position), item, "")
    for item, reason in plan.queue.held_snapshot():
        add("", item, reason)
    for symbol, timeframe in plan.tradier_owned:
        rows.append(["", symbol, timeframe, "False"] + [""] * 9 + ["tradier_owned"])
    return rows


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    error = validate_args(args)
    if error:
        parser.error(error)
    settings = Settings()
    try:
        asyncio.run(IbkrHistoryFetcher(settings.database_url, args, settings=settings).run())
    except Exception as error:  # BaseBatch already logged it and emitted failure
        print(f"ibkr history fetcher failed: {type(error).__name__}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed, metrics disabled: {error}")
    sys.exit(main())
