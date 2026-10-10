#!/usr/bin/env python3
"""ohlcv_history_fetcher.py -- the multi-provider OHLCV history fetcher (phase 189 plan 04;
generalized to the provider registry and renamed in phase 190, provider history plane
unification).

Concept: ohlcv_history_fetcher (docs/plans/2026-10-09-provider-history-plane-unification-
design.md; the phase 189 consolidation it generalizes:
docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md). A BaseBatch oneshot, not a
Ring 2 daemon. The loop is vendor-blind: every queue item dispatches through its provider's
registry entry, and the ibkr entry owns the concrete leaf mechanics. The external identity
strings (advisory lock name, JOB metric label, LOCK_HELD_MESSAGE, run status-file path,
systemd unit filenames) are frozen byte-identical by the phase 190 decision -- independent
processes parse or key on them -- so only code identifiers rename. Until the 190-06 cutover
installs the updated unit, a thin compatibility shim at the old ibkr_history_fetcher.py path
keeps the live unit fetchable.

One process owns
the IBKR history connection (CD-01), works a priority queue over the ohlcv_coverage ledger one
(symbol, timeframe) at a time (CD-06), records every outcome in the ledger (CD-03/CD-05), and
promotes the derived grid in the same pass (CD-07). It is the only CLI for IBKR history:
it absorbed the historical pipeline's CLI (same flag names and meanings where they exist;
plan 189-08 turned that script into the helper library _history_fetch.py) and the run-level
stages of the former nightly backfill script (split detection, the daily and grid
derivation stages, the D7 run status file); plan 189-07 deleted the nightly.

Named symbols (--symbols) are asked even when their series is current: an operator or a
tool that names a series (ops_split_detect's re-fetch, ops_head_rerun) wants it asked now.
The recurring timer run names none, so the current hold still spares the one IBKR stream.

Two lanes, one queue (plan 189-10 Task 1, as amended by 185-46; _fetch_queue.py): every
active name's 1d and 5m are asked after each session close since their latest stored bar,
widened to overlap the stored tail (the update lane); on one session in every
infra.backfill.gap_fill_interval_days a series plans its full depth instead (the gap-fill
lane); a default run also asks the weekly parity sample's vendor 15m and 1h. A 1d item is due
by the session calendar and the request ledger, never held back for a vendor (the Tradier hold
is gone: IBKR is the 1d primary, owner decision 2026-10-07), and ranks ahead of every 5m item.
The overlap is judged after the loop: a restated 1d overlap (a split, an unexplained
difference, a restated close) or a rescaled 5m overlap escalates the name to a full-depth
re-fetch in this run, on the open connection and under this run's lock, in the order record,
re-fetch, derive (todo 507; D2 counts only a fetch made after the recording as post-split).

Flow (CD-01/CD-02/CD-07):

    FetcherLock.acquire()                  -- fail fast: held elsewhere -> exit 0, lock_held
      -> resolve scopes -> candidates      -- APR infra.backfill.default_scopes union, deduped,
                                              plus the weekly parity sample (default run)
      -> IBKRProvider.connect()            -- unreachable -> raise, status failure (CD-08)
      -> loop until budget or queue empty:
           row = queue.next(pool, visited) -- reads ohlcv_coverage, pure ranking
           fetch_item_with_retries(...)    -- stall-bounded, atomic chunk + coverage writes;
                                              the item's lane sets its span
           record_fetch_outcome(...)       -- one ledger write per item (not on gateway loss)
      -> overlap judgment: 1d splits recorded (185-22), 1d and 5m breaches collected
      -> escalation re-fetch of those names, full depth, same connection, same lock
      -> disconnect; final D1 sink flush
      -> daily stage + 1d ledger refresh -> grid stage
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
its own daily caller at cutover (plan 189-06/07).

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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill import _empty_history as empty_history  # noqa: E402
from scripts.infrastructure.backfill import _history_fetch  # noqa: E402
from scripts.infrastructure.backfill._fetch_queue import (  # noqa: E402
    DAILY_TF,
    CoverageRow,
    DailyRule,
    LaneConfig,
    OverlapVerdict,
    PriorityQueue,
    ProviderPlan,
    QueueConfig,
    RankedItem,
    default_provider,
    gap_fill_due,
    judge_overlap,
    load_lane_config,
    load_provider_plan,
    load_queue_config,
    parity_sample,
    parity_week_start,
    reconcile_after,
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
from scripts.ops.bars.ops_split_detect import (  # noqa: E402
    SPLIT_RULE_KEYS,
    _unexplained_reporter,
    act_on_detections,
    rescale_reporter,
    split_rule_from_apr,
)
from services.bar_reconciliation_audit import NIGHTLY_STATUS_FILE  # noqa: E402
from services.ohlcv_coverage_writer import (  # noqa: E402
    rebuild_from_stored_state,
    record_fetch_outcome,
    refresh_1d_bounds,
    reset_failures,
)
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id  # noqa: E402
from services.split_detection import judge_overlap_pairs, overlap_pairs  # noqa: E402
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

# FROZEN (phase 190 decision): the metric job label, the log-file name (BaseBatch derives
# logs/<job_name>.log from it) and the metric series identity stay byte-identical across the
# code-identifier rename; renaming it would start a new job_completed_total series and move
# the log file under any dashboard or operator tailing the old path.
JOB = "ibkr-history-fetcher"
_OBSERVATION_CALLER = JOB
_WRITER_ROLE = "bar_derivation_writer"
_DIMENSIONS = ("backfill", "compute", "compute_1d", "live")
_DERIVATION_SCRIPT = project_root / "services" / "bar_derivation.py"
# The update lane's intraday overlap applies to the grid source timeframe: 5m is the one
# intraday series stored direct (the grid derives 15m and 1h from it).
_INTRADAY_UPDATE_TF = "5m"
# The parity sample's vendor timeframes (archive-bound in the item, _history_fetch._ARCHIVE_TFS).
_PARITY_TFS = ("15m", "1h")
# The split judgment's APR keys (threshold.seam.*, as ops_split_detect reads them).
_SEAM_KEYS = ("threshold.seam.rel_tol", "threshold.seam.min_run", "threshold.seam.ratio_snap_tol")
_FACT_MONITOR = "bar_split_detection"
_FACT_METRIC = "unexplained_overlap_difference"
# The reason the 1d judge gives a name it newly held (services/bar_hold.py, plan 185-51).
_HELD_REASON = "unclassified_rescale"

# APR keys read once at startup. Missing keys raise: the migrations seed them (432).
# (The per-provider planner inputs, inter-item pause included, read through ProviderPlan.)

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
    "provider",
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
    "lane",
    "due_reason",
)
# Names holding 5m rows and vendor archive rows: the parity sample's eligible set.
_PARITY_ELIGIBLE_SQL = (
    "SELECT c.symbol FROM ohlcv_coverage c WHERE c.timeframe = '5m' "
    "AND c.earliest_timestamp IS NOT NULL AND c.symbol = ANY($1::text[]) "
    "AND EXISTS (SELECT 1 FROM ohlcv_intraday_raw_archive a "
    "WHERE a.symbol = c.symbol AND a.timeframe = ANY($2::text[]))"
)
# A corporate action recorded after the series' last applied ingress load before this run:
# the stored rows have not been reconciled with it, so the escalation re-fetch may rewrite them.
# A void row (migration 461) retracts an action and never licenses a rewrite.
_WAIVER_SQL = (
    "SELECT EXISTS (SELECT 1 FROM corporate_action c WHERE c.symbol = $1 "
    "AND c.action_type <> 'void' AND c.recorded_at > "
    "COALESCE((SELECT max(l.loaded_at) FROM ohlcv_load l WHERE l.symbol = $1 "
    "AND l.timeframe = $2 AND l.source = 'ibkr' AND l.outcome = 'applied' "
    "AND l.loaded_at < $3), '-infinity'::timestamptz))"
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
        "--overlap-sessions",
        type=int,
        default=None,
        help=(
            "Re-ask the last N 1d sessions D1 already answers (default APR "
            "infra.backfill.update_overlap_sessions_1d). ops_split_detect passes its split "
            "re-fetch depth here."
        ),
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
        "--no-derive",
        action="store_true",
        help=(
            "Skip the run-end daily stage and the 1d ledger refresh: 1d answers land in D1 "
            "only, so the caller can gate a d2-v2 dry run before applying (189-10 Task 1b)."
        ),
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
    """The pipeline's explicit-timeframes rule and a non-negative --overlap-sessions;
    returns an error message or None."""
    if args.dimension in ("backfill", "compute_1d") and args.timeframes is None:
        return (
            f"--dimension {args.dimension} requires an explicit --timeframes: it includes "
            "symbols deliberately kept off the full timeframe stack (e.g. the 1d-only cohort)."
        )
    if getattr(args, "overlap_sessions", None) is not None and args.overlap_sessions < 0:
        return f"--overlap-sessions must be >= 0, got {args.overlap_sessions}"
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
    base = (_history_fetch._parse_contract_symbol(symbol) or (None,))[0]
    return symbol in wanted or base in wanted


@dataclass
class Candidates:
    """The resolved (symbol, timeframe) pairs and the instrument behind each symbol."""

    pairs: list[tuple[str, str]]
    instruments: dict[str, Any]
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
        for contract in contracts:
            instruments.setdefault(contract.symbol, contract)
            for tf in tfs:
                pairs.setdefault((contract.symbol, tf), None)
    return Candidates(list(pairs), instruments, sorted(unknown))


def completed_session_closes(now: datetime, n_sessions: int = 1) -> list[datetime]:
    """NYSE session closes at or before `now` (UTC), ascending, at least `n_sessions` of them
    when the calendar holds them (the lookback widens with n: two calendar days a session).

    One calendar for every candidate: today's universe is all NYSE-session equity, and the
    1d planner refuses any other calendar the same way (asset_agnostic caveat, as there).
    """
    lookback = _SESSION_LOOKBACK_DAYS + 2 * n_sessions
    sessions = nyse_sessions(now.date() - timedelta(days=lookback), now.date())
    return sorted(close for _open, close in sessions.values() if close <= now)


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
    tf_fetch_config: Mapping[str, tuple[int, bool]]
    overlap_sessions: int
    inter_item_pause_s: float
    lanes: LaneConfig
    # The last completed session's date: the gap-fill lane's slot is keyed on it.
    session_day: Any
    # The weekly parity sample's (symbol, timeframe) items (default runs only).
    parity: tuple[tuple[str, str], ...] = ()
    # Providers with candidates in this run: only these connect (a registry entry whose
    # provider has zero candidates is never constructed or connected).
    providers: frozenset[str] = frozenset()
    # Per-provider planner inputs (load_provider_plan): the dispatch hands each item's own
    # plan to its registry entry's fetch hook.
    plans: Mapping[str, ProviderPlan] = field(default_factory=dict)


def item_lane(plan: RunPlan, row: CoverageRow, *, full_scan: bool = False) -> tuple[str, bool, int]:
    """(lane, full_scan, overlap_days) for one item; pure.

    parity: the vendor sample, asked from its latest archive bar, never a full depth;
    gap_fill: the series' gap-fill session (or --full-scan), the full depth window;
    backfill: never fetched or last failed, the item plans the full depth by itself;
    update: since the latest stored bar, 5m widened by the overlap days (1d's overlap is the
    run-level session overlap the 1d planner adds).
    """
    if (row.symbol, row.timeframe) in plan.parity:
        return "parity", False, 0
    if full_scan or (
        plan.session_day is not None
        and gap_fill_due(
            row.symbol, row.timeframe, plan.session_day, plan.lanes.gap_fill_interval_days
        )
    ):
        return "gap_fill", True, 0
    if row.latest_timestamp is None or row.last_fetch_status != "ok":
        return "backfill", False, 0
    overlap = plan.lanes.update_overlap_days_5m if row.timeframe == _INTRADAY_UPDATE_TF else 0
    return "update", False, overlap


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
# Provider registry (phase 190 plan 04): one entry per vendor, the loop dispatches
# through entry.fetch and never sees vendor mechanics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderEntry:
    """One vendor's fetch mechanics behind the loop's dispatch (a config mapping behind
    the provider_factory seam, not a plugin framework: no discovery, no dynamic import).

    leaf_factory(settings, args) builds the run's leaf (IBKR: one socket per run); `fetch`
    is the hook the loop calls per item -- it owns that vendor's mechanics and returns the
    item's outcome; load_overlays loads the vendor's leaf-native APR overlays (soft
    fallback); connect_failure_label composes the startup connect failure (the ibkr entry
    keeps the "IBKR gateway unreachable at startup" wording).
    """

    name: str
    leaf_factory: Callable[[Any, Any], Any]
    fetch: Callable[..., Awaitable[ItemOutcome]]
    load_overlays: Callable[[Any], None]
    connect_failure_label: str


def _ibkr_leaf_factory(settings: Any, args: Any) -> Any:
    """The IBKR leaf construction (moved from the fetcher's _default_provider): one socket
    per run, client id from the CLI flag. The concrete IBKRProvider import lives in this
    module's registry entry, the fetcher-family's one boundary allow-list entry."""
    return IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=args.client_id)


def _ibkr_load_overlays(settings: Any) -> None:
    """The ibkr entry's leaf-native APR overlays (chunk days, hist timeouts, retries,
    venue fallback, rate limit). Soft-fallback contract: a missing key or an unreachable
    DB logs and keeps the leaf module's defaults -- these are leaf-native limits, unlike
    planner inputs, which raise (load_provider_plan)."""
    _history_fetch._load_ibkr_chunk_days_config(settings)
    _history_fetch._load_ibkr_hist_timeout_config(settings)
    _history_fetch._load_ibkr_retry_config(settings)
    _history_fetch._load_ibkr_venue_fallback_config(settings)
    _history_fetch._load_ibkr_rate_limit_config(settings)


def _ibkr_entry_fetch(
    fetch_fn: Callable[..., Awaitable[ItemOutcome]] = fetch_item_with_retries,
) -> Callable[..., Awaitable[ItemOutcome]]:
    """The ibkr entry's fetch hook over the 189-proven item path: fetch_item_with_retries
    with the IBKR FetchContext mechanics (qualification, head floors, FX/crypto derive and
    venue fallback are reachable only through this hook). `fetch_fn` is the constructor
    seam, so existing test injection keeps working. The hook carries the item's ProviderPlan
    in (ctx.plan and the provider_plan kwarg) so the item reads its vendor semantics from
    the plan, never from a module constant."""

    async def fetch(
        ctx: Any,
        leaf: Any,
        instrument: Any,
        row: Any,
        *,
        plan: ProviderPlan | None,
        full_scan: bool,
        overlap_days: int = 0,
        refetch: bool = False,
        waived: bool = False,
        config: Any,
        reconnect: Callable[[], Awaitable[bool]],
        on_tick: Callable[[], None] | None,
    ) -> ItemOutcome:
        ctx.plan = plan
        outcome = await fetch_fn(
            ctx,
            instrument,
            row,
            full_scan=full_scan,
            overlap_days=overlap_days,
            refetch=refetch,
            waived=waived,
            config=config,
            reconnect=reconnect,
            on_tick=on_tick,
            provider_plan=plan,
        )
        # The ibkr fetch path labels its outcomes (the loop records them provider-labeled).
        return replace(outcome, provider=row.provider)

    return fetch


_PROVIDER_REGISTRY: dict[str, ProviderEntry] = {
    "ibkr": ProviderEntry(
        name="ibkr",
        leaf_factory=_ibkr_leaf_factory,
        fetch=_ibkr_entry_fetch(),
        load_overlays=_ibkr_load_overlays,
        connect_failure_label="IBKR gateway",
    )
}


def _unknown_providers(queue: Any, registry_names: Iterable[str]) -> list[str]:
    """Ranked or held providers without a registry entry. The loop would hit them
    mid-dispatch, so prepare() refuses the plan up front."""
    known = set(registry_names)
    providers = {item.row.provider for item in queue.ranked_snapshot()}
    providers |= {item.row.provider for item, _ in queue.held_snapshot()}
    return sorted(providers - known)


def _read_infra_apr(conn: Any) -> dict[str, str]:
    """Every infra.* APR value in one read; the per-provider planner inputs go through
    load_provider_plan (which raises on a missing planner input and keeps the one
    leaf-native window fallback)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'infra.%'"
        )
        return {str(k): str(v) for k, v in cur.fetchall()}


# ---------------------------------------------------------------------------
# The fetcher
# ---------------------------------------------------------------------------


def _sd_notify_watchdog() -> None:
    """WATCHDOG=1 to systemd; a no-op outside a unit (no NOTIFY_SOCKET)."""
    if not os.getenv("NOTIFY_SOCKET"):
        return
    import sdnotify  # type: ignore[import-untyped]

    sdnotify.SystemdNotifier().notify("WATCHDOG=1")


class OHLCVHistoryFetcher(BaseBatch):
    """The multi-provider OHLCV history fetcher oneshot (CD-01/CD-02/CD-07), provider-parameterized
    since phase 190 plan 04: a registry (`_PROVIDER_REGISTRY`, one entry per vendor) maps a
    provider name to its leaf factory, item-fetch hook and overlay loader, and the loop
    dispatches each queue item through its entry's fetch -- vendor mechanics are reachable
    only through the entry, never from the loop.

    Constructor seams exist for tests and replace exactly one dependency each: the provider
    registry (default _PROVIDER_REGISTRY; a custom one passes through untouched), the
    ibkr entry's leaf (provider_factory) and item fetch (fetch_fn), the lock name or the
    whole lock, the run plan (reads), the stage runner (subprocess), the psycopg connect,
    the contract source, the watchdog notifier, the status file path, the 1d overlap judge
    (records splits), the 5m waiver read and the overlap finding reporter.
    """

    job_name = JOB
    compute_version = "190.0"

    def __init__(
        self,
        db_dsn: str,
        args: argparse.Namespace,
        *,
        settings: Settings | None = None,
        registry: Mapping[str, ProviderEntry] | None = None,
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
        # FROZEN (phase 190 decision): the run status-file path (logs/ibkr_history_fetcher_
        # status.json, services/bar_reconciliation_audit.py NIGHTLY_STATUS_FILE) is read by the
        # D7 audit's nightly_skipped check, so writer and reader would have to move in one
        # commit; the path stays byte-identical across the rename.
        status_file: Path = NIGHTLY_STATUS_FILE,
        overlap_judge: Callable[[Any, str, LaneConfig], Awaitable[Mapping[str, str]]] | None = None,
        waiver: Callable[[Any, str, str, datetime], Awaitable[bool]] | None = None,
        report_overlap: Callable[[str, str, OverlapVerdict], None] | None = None,
    ) -> None:
        super().__init__(db_dsn)
        self.args = args
        self.settings = settings or Settings()
        self._provider_factory = provider_factory
        self._fetch_fn = fetch_fn
        self._registry = self._bind_registry(registry)
        self._leaves: dict[str, Any] = {}
        self._lock_name = lock_name
        self._lock_factory = lock_factory or (
            lambda: FetcherLock(
                self.settings.database_url,
                holder=f"{JOB}:{self.args.client_id}",
                name=self._lock_name,
            )
        )
        self._prepare = prepare or self.prepare
        self._context_factory = context_factory or self._default_context
        self._run_stage = stage_runner or self._run_subprocess
        self._connect = connect or (lambda: _history_fetch.connect_db(self.settings))
        self._contracts_for = contracts_for or _default_contracts_for(
            self.settings, args.include_rolled
        )
        self._notify = notify
        self._status_file = status_file
        self._overlap_judge = overlap_judge or self._judge_daily_overlap
        self._waiver = waiver or self._waiver_recorded
        self._report_overlap = report_overlap or self._report_overlap_fact
        self._tick_s: float | None = None
        self.summary: dict[str, Any] = {}

    # -- seams' defaults ----------------------------------------------------

    def _bind_registry(
        self, registry: Mapping[str, ProviderEntry] | None
    ) -> dict[str, ProviderEntry]:
        """The run's registry: the module entries with this fetcher's constructor seams
        bound to the ibkr entry (the seams exist to inject IBKR test fakes: provider_factory
        is the injected leaf, fetch_fn the injected item mechanics, both read at call time).
        A custom registry's foreign entries pass through untouched; a custom registry that
        reuses the module ibkr entry still gets the seams."""
        bound = dict(registry) if registry is not None else dict(_PROVIDER_REGISTRY)
        entry = bound.get("ibkr")
        if entry is not _PROVIDER_REGISTRY.get("ibkr"):
            return bound

        def leaf(settings: Any, args: Any) -> Any:
            if self._provider_factory is not None:
                return self._provider_factory()
            return entry.leaf_factory(settings, args)

        fetch = (
            entry.fetch
            if self._fetch_fn is fetch_item_with_retries
            else _ibkr_entry_fetch(self._fetch_fn)
        )
        bound["ibkr"] = replace(entry, leaf_factory=leaf, fetch=fetch)
        return bound

    def _default_context(self, provider: Any, plan: RunPlan, fetch_run_id: str) -> FetchContext:
        conn = self._connect()
        try:
            empty_ranges = empty_history.load(conn, _history_fetch._EMPTY_HISTORY_PROVIDER)
            reverify_days = empty_history.load_reverify_days(conn)
            fresh_heads = empty_history.load_fresh_heads(
                conn, _history_fetch._EMPTY_HISTORY_PROVIDER, reverify_days
            )
            first_bars = empty_history.load_first_bars(conn, list(plan.candidates.instruments))
        finally:
            conn.close()
        sink = ObservationSink(
            self._connect(),
            caller=_OBSERVATION_CALLER,
            max_buffer_rows=_history_fetch._load_observation_batch_rows(self.settings),
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
        """Resolve scopes, candidates, the parity sample and the queue. Reads only: shared by
        the dry run."""
        conn = self._connect()
        try:
            config = load_queue_config(conn)
            lanes = load_lane_config(conn)
            infra_values = _read_infra_apr(conn)
        finally:
            conn.close()
        # One ProviderPlan per registered provider: the planner inputs raise when missing,
        # the leaf-native window keeps its fallback (load_provider_plan's contract).
        plans = {
            name: load_provider_plan(name, infra_values.get, depth_tfs=tuple(config.depth_days))
            for name in self._registry
        }
        default_plan = plans.get(default_provider())
        tf_fetch_config = _history_fetch._load_tf_fetch_config(self.settings)
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
        now = datetime.now(UTC)
        parity = await self._parity_items(pool, candidates, lanes, tf_fetch_config, now)
        pairs = list(dict.fromkeys([*candidates.pairs, *parity]))
        candidates = Candidates(pairs, candidates.instruments, candidates.unknown_timeframes)
        closes = completed_session_closes(now, lanes.reconcile_interval_sessions)
        last_close = closes[-1] if closes else None
        # Named symbols bypass every hold (module docstring): a caller that names a series
        # wants it asked even when its last fetch settled after the latest close.
        named = bool(self.args.symbols)
        daily = (
            None
            if named or last_close is None
            else DailyRule(last_close, reconcile_after(closes, lanes.reconcile_interval_sessions))
        )
        week_start = parity_week_start(now.date())
        queue = PriorityQueue(
            config,
            pairs,
            now.date(),
            current_after=None if named else last_close,
            daily=daily,
            current_after_by_series=dict.fromkeys(parity, week_start),
            plan=default_plan,
        )
        await queue.load(pool)
        # Fail fast, never mid-run: every provider the plan could dispatch must be registered.
        unknown = _unknown_providers(queue, self._registry)
        if unknown:
            raise RuntimeError(
                f"no provider registry entry for {unknown}: every provider in the run's "
                "plan must be registered"
            )
        overlap_sessions = (
            self.args.overlap_sessions
            if self.args.overlap_sessions is not None
            else lanes.update_overlap_sessions_1d
        )
        return RunPlan(
            config=config,
            queue=queue,
            candidates=candidates,
            tf_fetch_config=tf_fetch_config,
            overlap_sessions=overlap_sessions,
            inter_item_pause_s=default_plan.inter_item_pause_s if default_plan else 0.0,
            lanes=lanes,
            session_day=None if last_close is None else last_close.date(),
            parity=parity,
            providers=frozenset({default_provider()}) if pairs else frozenset(),
            plans=plans,
        )

    def _is_default_run(self) -> bool:
        args = self.args
        return args.dimension is None and args.timeframes is None and not args.symbols

    async def _parity_items(
        self,
        pool: Any,
        candidates: Candidates,
        lanes: LaneConfig,
        tf_fetch_config: Mapping[str, Any],
        now: datetime,
    ) -> tuple[tuple[str, str], ...]:
        """This ISO week's parity sample (design section 7): vendor 15m and 1h for
        infra.backfill.grid_parity_sample_names_per_week names holding 5m and archive rows.
        Default runs only: an explicit run asks exactly what it names."""
        tfs = [tf for tf in _PARITY_TFS if tf in tf_fetch_config]
        if not self._is_default_run() or lanes.parity_names_per_week <= 0 or not tfs:
            return ()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _PARITY_ELIGIBLE_SQL, sorted(candidates.instruments), list(_PARITY_TFS)
            )
        sample = parity_sample([r["symbol"] for r in rows], now.date(), lanes.parity_names_per_week)
        return tuple((symbol, tf) for symbol in sample for tf in tfs)

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
        held_i = _TSV_COLUMNS.index("held_reason")
        lane_i = _TSV_COLUMNS.index("lane")
        due_i = _TSV_COLUMNS.index("due_reason")
        tf_i = _TSV_COLUMNS.index("timeframe")
        bands = Counter(
            (
                f"lane={r[lane_i]} tf={r[tf_i]} due={r[due_i] or '-'}"
                if r[held_i] == ""
                else f"held={r[held_i]}"
            )
            for r in rows
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
        self._load_overlays(plan.providers)
        fetch_run_id = new_fetch_run_id()
        # Exact format the pipeline printed: ops_head_rerun parses it.
        print(f"  fetch_run_id: {fetch_run_id}")

        # One leaf per provider with candidates in this run, cached for the run (IBKR's
        # single socket means one IBKRProvider instance); a zero-candidate provider is
        # never constructed or connected.
        leaves: dict[str, Any] = {}
        for name in sorted(plan.providers):
            entry = self._registry[name]
            leaf = entry.leaf_factory(self.settings, self.args)
            if not await leaf.connect():
                raise RuntimeError(f"{entry.connect_failure_label} unreachable at startup")
            leaves[name] = leaf
        self._leaves = leaves
        self._notify()
        run_started_at = datetime.now(UTC)
        primary = leaves.get(default_provider()) or next(iter(leaves.values()), None)
        ctx: Any = None
        escalation_code = 0
        try:
            ctx = self._context_factory(primary, plan, fetch_run_id)
            loop = await self._loop(pool, plan, ctx)
            if not loop.gateway_lost:
                escalation_code = await self._escalate(
                    pool, plan, ctx, loop, fetch_run_id, run_started_at
                )
        finally:
            for leaf in self._leaves.values():
                try:
                    await leaf.disconnect()
                except Exception as error:  # a dead socket may refuse a clean disconnect
                    logger.warning("ibkr_history_fetcher.disconnect_failed", error=str(error))
            if ctx is not None:
                self._final_flush(ctx)
        stage_codes = {"escalation": escalation_code, **await self._run_end_stages(ctx, loop)}
        sla_breached = await self._sla_breached(pool, plan)
        self.summary = {
            "fetch_run_id": fetch_run_id,
            **loop.counts(),
            "lanes": dict(sorted(loop.lanes.items())),
            "escalated": dict(loop.escalated),
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

    async def _loop(self, pool: Any, plan: RunPlan, ctx: Any) -> _LoopState:
        budget_min = (
            self.args.budget_minutes
            if self.args.budget_minutes is not None
            else plan.config.run_budget_minutes
        )
        deadline = time.monotonic() + budget_min * 60
        state = _LoopState()
        visited: set[tuple[str, str, str]] = set()
        while True:
            if time.monotonic() >= deadline:
                state.budget_exhausted = True
                break
            row = await plan.queue.next(pool, visited)
            if row is None:
                break
            key = (row.provider, row.symbol, row.timeframe)
            if key in visited:  # the queue handed back a visited item: never fetch twice
                logger.error(
                    "ibkr_history_fetcher.queue_repeated_item",
                    provider=row.provider,
                    symbol=row.symbol,
                    tf=row.timeframe,
                )
                break
            visited.add(key)
            lane, full_scan, overlap_days = item_lane(plan, row, full_scan=self.args.full_scan)
            state.lanes[lane] += 1
            outcome = await self._fetch_one(
                plan, ctx, row, full_scan=full_scan, overlap_days=overlap_days
            )
            self._notify()
            if outcome.gateway_lost:
                # The gateway, not the item, failed: nothing is charged to the series (CD-05).
                state.gateway_lost = f"{row.provider}/{row.symbol}/{row.timeframe}"
                break
            self._record_outcome(ctx, outcome)
            state.add(outcome)
            if outcome.overlap_pairs:
                verdict = judge_overlap(
                    outcome.overlap_pairs,
                    plan.lanes.basis_tolerance_bp,
                    escalate_on_restated=False,
                )
                if verdict.escalate:
                    state.overlap_breaches[(row.provider, row.symbol, row.timeframe)] = verdict
            item_plan = plan.plans.get(row.provider)
            await asyncio.sleep(
                item_plan.inter_item_pause_s if item_plan is not None else plan.inter_item_pause_s
            )
        return state

    async def _fetch_one(
        self,
        plan: RunPlan,
        ctx: Any,
        row: Any,
        *,
        full_scan: bool,
        overlap_days: int = 0,
        refetch: bool = False,
        waived: bool = False,
    ) -> ItemOutcome:
        """Dispatch the item through its provider's registry entry (T-190-13): the loop
        never calls a provider-specific path, and an entry failure surfaces as the item's
        error outcome, never a fallback to another vendor's mechanics."""
        try:
            entry = self._registry[row.provider]
            leaf = self._leaves[row.provider]
            instrument = plan.candidates.instruments[row.symbol]
            return await entry.fetch(
                ctx,
                leaf,
                instrument,
                row,
                plan=plan.plans.get(row.provider),
                full_scan=full_scan,
                overlap_days=overlap_days,
                refetch=refetch,
                waived=waived,
                config=plan.config,
                reconnect=leaf.connect,
                on_tick=self._notify,
            )
        except Exception as error:
            logger.error(
                "ibkr_history_fetcher.item_dispatch_failed",
                provider=row.provider,
                symbol=row.symbol,
                timeframe=row.timeframe,
                error=str(error),
                error_type=type(error).__name__,
            )
            return ItemOutcome(
                row.symbol,
                row.timeframe,
                "error",
                provider=row.provider,
                error=f"{type(error).__name__}: {error}",
            )

    # -- the update lane's escalation (plan 189-10 Task 1, todo 507) --------------------

    async def _escalate(
        self,
        pool: Any,
        plan: RunPlan,
        ctx: Any,
        loop: _LoopState,
        fetch_run_id: str,
        run_started_at: datetime,
    ) -> int:
        """Judge the run's overlaps and re-fetch every breached name at full depth, in this
        run, on the open connection and under this run's lock. Returns 0, or 1 when an
        escalation could not complete (the run is then partial).

        Order (todo 507): the 1d judge records splits first (corporate_action), then the
        re-fetch asks the whole 1d depth (answered after the recording, so D2 counts it as
        post-split), then the run-end daily stage derives. A 5m breach is re-fetched through
        the waived grid writer only when a corporate action recorded after the series' last
        applied load explains it; without one the ingress contract would refuse the rewrite,
        so the finding is recorded instead and the run is partial.
        """
        failed = False
        reasons_1d: Mapping[str, str] = {}
        if loop.touched_1d:
            try:
                reasons_1d = await self._overlap_judge(pool, fetch_run_id, plan.lanes)
                # A newly held name (plan 185-51) is a new integrity fact: the run is partial.
                # It is still re-fetched below (D1 keeps the vendor's restated answer for the
                # decision); the daily stage skips it, so no rewrite is applied.
                failed = any(r == _HELD_REASON for r in reasons_1d.values())
            except Exception as error:  # noqa: BLE001 - loud, partial; derivation still runs
                # As when split detection was a stage subprocess: a failed judgment fails the
                # run's escalation code (partial), never the daily stage of the touched names.
                logger.error(
                    "ibkr_history_fetcher.overlap_judge_failed",
                    error=str(error),
                    error_type=type(error).__name__,
                )
                failed = True
        targets: list[tuple[str, str, str, str, bool]] = []
        for symbol in sorted(reasons_1d):
            targets.append((default_provider(), symbol, DAILY_TF, reasons_1d[symbol], False))
        for (provider, symbol, timeframe), verdict in sorted(loop.overlap_breaches.items()):
            if await self._waiver(pool, symbol, timeframe, run_started_at):
                targets.append((provider, symbol, timeframe, str(verdict.reason), True))
            else:
                self._report_overlap(symbol, timeframe, verdict)
                loop.escalated[f"{symbol}/{timeframe}"] = "unwaived_overlap_breach"
                failed = True
        for provider, symbol, timeframe, reason, waived in targets:
            if symbol not in plan.candidates.instruments:
                logger.error("ibkr_history_fetcher.escalation_unknown_symbol", symbol=symbol)
                failed = True
                continue
            loop.escalated[f"{symbol}/{timeframe}"] = reason
            logger.warning(
                "ibkr_history_fetcher.escalation_refetch",
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                reason=reason,
                waived=waived,
            )
            row = CoverageRow(symbol, timeframe, None, None, None, 0, None, None, provider)
            outcome = await self._fetch_one(
                plan, ctx, row, full_scan=True, refetch=True, waived=waived
            )
            self._notify()
            if outcome.gateway_lost:
                loop.gateway_lost = f"{provider}/{symbol}/{timeframe} (escalation)"
                return 1
            self._record_outcome(ctx, outcome)
            loop.add(outcome)
            failed = failed or outcome.status == "error"
        return 1 if failed else 0

    async def _judge_daily_overlap(
        self, pool: Any, fetch_run_id: str, lanes: LaneConfig
    ) -> dict[str, str]:
        """The run's 1d overlap: splits recorded (185-22), rescales that are no split ratio held
        (plan 185-51, services/bar_hold.py), unexplained differences reported, all through
        ops_split_detect.act_on_detections, and every name to re-fetch with its reason."""
        keys = (*_SEAM_KEYS, *SPLIT_RULE_KEYS)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT config_key, config_value FROM config_state "
                "WHERE config_key = ANY($1::text[])",
                list(keys),
            )
            apr = {r["config_key"]: r["config_value"] for r in rows}
            missing = sorted(set(keys) - set(apr))
            if missing:
                raise RuntimeError(f"APR keys not set: {missing}")
            split_rule = split_rule_from_apr(apr)
            by_symbol = await overlap_pairs(conn, fetch_run_id)
            detected = judge_overlap_pairs(
                by_symbol,
                rel_tol=float(apr["threshold.seam.rel_tol"]),
                min_run=int(apr["threshold.seam.min_run"]),
                ratio_snap_tol=float(apr["threshold.seam.ratio_snap_tol"]),
                split_rule=split_rule,
            )
            reasons = dict(
                await act_on_detections(
                    conn,
                    detected,
                    split_rule=split_rule,
                    report_unexplained=_unexplained_reporter(self.settings),
                    report_rescale=rescale_reporter(self.settings),
                    recorded_by=JOB,
                    fetch_run_id=fetch_run_id,
                )
            )
        for symbol, pairs in sorted(by_symbol.items()):
            verdict = judge_overlap(
                [(float(r["prev_close"]), float(r["new_close"])) for r in pairs],
                lanes.basis_tolerance_bp,
                escalate_on_restated=True,
            )
            if verdict.escalate:
                reasons.setdefault(symbol, str(verdict.reason))
        return reasons

    async def _waiver_recorded(
        self, pool: Any, symbol: str, timeframe: str, before: datetime
    ) -> bool:
        async with pool.acquire() as conn:
            return bool(await conn.fetchval(_WAIVER_SQL, symbol, timeframe, before))

    def _report_overlap_fact(self, symbol: str, timeframe: str, verdict: OverlapVerdict) -> None:
        """An unexplained overlap breach as an integrity fact (the split detector's monitor)."""
        import psycopg

        from src.core.integrity_monitor import emit_integrity_fact_sync

        with psycopg.connect(self.settings.database_url, autocommit=True) as fact_conn:
            emit_integrity_fact_sync(
                fact_conn,
                _FACT_MONITOR,
                symbol,
                _FACT_METRIC,
                verdict.median_ratio,
                1.0,
                False,
                None,
            )
        logger.error(
            "ibkr_history_fetcher.overlap_breach_unwaived",
            symbol=symbol,
            timeframe=timeframe,
            median_ratio=verdict.median_ratio,
            n_pairs=verdict.n_pairs,
            n_restated=verdict.n_restated,
        )

    def _record_outcome(self, ctx: Any, outcome: ItemOutcome) -> None:
        conn = ctx.get_conn()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            record_fetch_outcome(
                cur,
                outcome.symbol,
                outcome.timeframe,
                outcome.status,
                datetime.now(UTC),
                provider=outcome.provider,
            )

    def _final_flush(self, ctx: Any) -> None:
        """The pipeline's best-effort final D1 flush: an item that died mid-fetch may have left
        buffered answers. Never masks the primary outcome."""
        try:
            if ctx.sink.pending():
                _history_fetch._flush_capture(ctx.sink, self.settings)
        except Exception as error:  # noqa: BLE001
            logger.error("ibkr_history_fetcher.final_flush_failed", error=str(error))

    async def _run_end_stages(self, ctx: Any, loop: _LoopState) -> dict:
        """The daily stage and its ledger refresh, then the grid stage.

        Splits were judged, recorded and re-fetched in-process before this (_escalate), so the
        daily stage derives a split symbol's history on one scale (185-22); the daily stage
        runs before the grid stage so the two derivation writers never overlap. Under the
        lock no other IBKR writer exists, so no lane-guard exclude file is needed.
        """
        codes: dict[str, int] = {}
        python = sys.executable
        if loop.touched_1d and self.args.no_derive:
            logger.info(
                "ibkr_history_fetcher.daily_stage_skipped",
                reason="no_derive",
                n_symbols=len(loop.touched_1d),
            )
        elif loop.touched_1d:
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
        """Refresh the 1d ledger bounds from the rows D2 just wrote. No fetch bookkeeping
        is written: promotion reads bar_integrity verdicts (plan 185-41)."""
        conn = ctx.get_conn()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            refresh_1d_bounds(cur, touched)

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
            await _history_fetch.seed_roll_chain(self.settings, db)
        finally:
            await db.close()

    def _load_overlays(self, providers: Iterable[str]) -> None:
        """The run's APR overlays, split by owner (phase 190 plan 04): the provider-neutral
        loaders stay fetcher-owned; each provider in the run loads its leaf-native overlays
        through its registry entry (soft fallback, never a raise)."""
        settings = self.settings
        _history_fetch._load_ohlcv_insert_batch_size_config(settings)
        _history_fetch._load_gap_cluster_max_days_config(settings)
        for name in providers:
            self._registry[name].load_overlays(settings)

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
    lanes: Counter[str] = field(default_factory=Counter)
    # Update-lane overlaps the 5m judge found rescaled, and every escalation with its reason.
    overlap_breaches: dict[tuple[str, str], OverlapVerdict] = field(default_factory=dict)
    escalated: dict[str, str] = field(default_factory=dict)

    def add(self, outcome: ItemOutcome) -> None:
        if outcome.status == "ok":
            self.n_ok += 1
        elif outcome.status == "no_data":
            self.n_no_data += 1
        else:
            self.n_error += 1
        self.n_bars += outcome.n_bars
        self.n_grid_source_rows += outcome.n_grid_source_rows
        # Only a clean 1d item is derived and its ledger bounds refreshed (189-03 interface).
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


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def dry_run_rows(plan: RunPlan) -> list[list[str]]:
    """TSV rows: the queue in order (position 1..n), then held series, each with its lane
    and (1d) its due reason."""
    rows: list[list[str]] = []
    due_reason = getattr(plan.queue, "due_reason", lambda symbol, timeframe: "")

    def add(position: str, item: RankedItem, reason: str) -> None:
        r = item.row
        rows.append(
            [
                position,
                r.symbol,
                # The provider column (phase 190 plan 04): today every row is the ibkr
                # plane; 190-06's parity gate diffs columns, so this is additive.
                r.provider,
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
                item_lane(plan, r)[0],
                due_reason(r.symbol, r.timeframe) if reason == "" else "",
            ]
        )

    for position, item in enumerate(plan.queue.ranked_snapshot(), start=1):
        add(str(position), item, "")
    for item, reason in plan.queue.held_snapshot():
        add("", item, reason)
    return rows


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    error = validate_args(args)
    if error:
        parser.error(error)
    settings = Settings()
    try:
        asyncio.run(OHLCVHistoryFetcher(settings.database_url, args, settings=settings).run())
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
