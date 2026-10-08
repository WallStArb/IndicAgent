"""One IBKR history queue item: fetch a (symbol, timeframe), bounded against hangs
(phase 189 plan 03; design docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md).

The IBKR history fetcher works its priority queue one (symbol, timeframe) at a time. This
module is that unit of work, moved out of the historical pipeline's monolithic per-symbol
loop (the historical pipeline script's main()._run_fetch_stage, now _history_fetch.py's
helpers) so it can be tested alone and so a single name can never hold the run:

- CD-01: one fetcher, one item at a time; the queue decides order, this module decides how
  one item is fetched.
- CD-04: every provider-returned chunk, archive timeframes (15m/1h) and grid timeframes
  (5m/1d/1m) alike, commits through _intraday_persist.persist_chunk_atomically together with
  its request rows and its ohlcv_coverage update, so the ledger never describes bars that did
  not land and no answered request outruns its bars.
- CD-05: the outcome is classified so the ledger only charges genuine failures. A correct
  empty answer is 'no_data', never 'error'; a lost gateway is not the item's fault at all.
- CD-08: a progress-aware stall bound cancels an item whose provider went silent, reconnects
  the client and retries a bounded number of times. ibkr.py's own per-request wait_for has been
  seen not to fire (2026-07-05 and 2026-10-02 incidents), so this is the in-process layer; the
  systemd WatchdogSec of plan 04 covers the case where asyncio timers never fire at all.

The fetch helpers (gap detection, store paths, per-contract futures, 1m derivation, D1
capture) live in _history_fetch.py, the CLI-free helper library plan 189-08 made of the
historical pipeline. Every timeframe stores real provider bars only (plan 185-32), so no
item writes a placeholder or fetch bookkeeping. All provider access goes through IBKRProvider methods;
src/providers/ibkr.py stays the only ib_async importer.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from scripts.infrastructure.backfill import _empty_history as empty_history
from scripts.infrastructure.backfill import _history_fetch
from scripts.infrastructure.backfill._d1_gaps import (
    detect_gaps_1d_from_d1,
    detect_gaps_from_record,
    load_answered_windows,
    midnight_utc,
    with_overlap_window,
)
from scripts.infrastructure.backfill._history_fetch import (
    _1M_DAYS_CRYPTO,
    _1M_DAYS_FX,
    _ARCHIVE_TFS,
    _EMPTY_HISTORY_PROVIDER,
    _RECORD_PLAN_TFS,
    _TF_MINUTES,
    _capture_kwargs,
    _fetch_start,
    _flush_capture,
    _insert_archive_rows,
    _insert_market_data_rows,
    _insert_market_data_rows_waived,
    aggregate_bars_from_1m,
    cluster_gap_ranges,
    detect_gaps,
    fetch_bars,
    fetch_per_contract,
    real_bars_only_for,
)
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import (
    DESTINATION_ARCHIVE,
    DESTINATION_GRID,
    FETCH_STATUSES,
    CoverageDelta,
)
from services.ohlcv_ingress_contract import read_stored
from src.core.models import AssetClass
from src.intelligence.bars.gap_plan import expected_grid_slots
from src.intelligence.bars.sessions import nyse_sessions
from src.providers import ibkr
from src.providers.base import EmptyHistory

logger = structlog.get_logger(__name__)

# The 5m grid is the source the 15m/1h grid is derived from (services/bar_derivation.py).
_GRID_SOURCE_TF = "5m"
# Timeframes the FX/crypto 1m deep fetch derives when the direct fetch stored nothing (kept
# from the pipeline for asset_agnostic; no FX/crypto name is active today). 1d left this
# fallback in plan 185-18 task 1b: its grid rows are the daily derivation's.
_FX_DERIVED_TFS = frozenset({"5m", "15m", "1h"})
_FX_SOURCE_TF = "1m"

# The stall bound is checked this many times per stall_timeout_s. Derived check cadence, not a
# tunable: the bound itself is infra.ibkr.history_request_timeout (APR); three checks per
# bound cap how far past it a stall can run before cancellation at a third of the bound.
_STALL_CHECKS_PER_TIMEOUT = 3


@dataclass(frozen=True)
class ItemOutcome:
    """How one queue item ended. The fetcher writes `status` to ohlcv_coverage through
    record_fetch_outcome unless `gateway_lost` is set (a lost gateway is not charged)."""

    symbol: str
    timeframe: str
    status: str
    n_bars: int = 0
    # 5m grid rows written this item (offered to the insert; re-affirmed duplicates count).
    # Plan 04 promotes the derived 15m/1h grid when this is non-zero.
    n_grid_source_rows: int = 0
    attempts: int = 1
    gateway_lost: bool = False
    error: str | None = None
    elapsed_s: float = 0.0
    # 1d only: the item captured bars into D1 from this window start. The caller runs the
    # daily derivation stage for these symbols and refreshes the 1d ledger bounds from
    # here (plan 185-18 task 1b: D2 is the sole 1d writer, so fetch_item never stores 1d).
    derive_1d_since: datetime | None = None
    # Update lane (plan 189-10): (stored close, fresh close) for every fresh grid bar whose
    # slot was already stored, read before the write. The fetcher judges them
    # (_fetch_queue.judge_overlap) and escalates a rescaled series in the same run.
    overlap_pairs: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in FETCH_STATUSES:
            raise ValueError(f"unknown item status {self.status!r}; expected {FETCH_STATUSES}")


class ProgressClock:
    """When the item last made progress (a request answered, a chunk persisted)."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._last = now()

    def touch(self) -> None:
        self._last = self._now()

    def age(self) -> float:
        return self._now() - self._last


class ItemStalled(Exception):
    """The item made no progress for the stall bound and was cancelled."""

    def __init__(self, elapsed_s: float) -> None:
        super().__init__(f"no progress for {elapsed_s:.1f}s")
        self.elapsed_s = elapsed_s


class GatewayLost(Exception):
    """The IBKR client is down and could not be reconnected: not the item's failure."""


async def run_with_stall_bound(
    make_coro: Callable[[], Awaitable[Any]],
    *,
    stall_timeout_s: float,
    clock: ProgressClock,
    on_tick: Callable[[], None] | None = None,
) -> Any:
    """Run one item, cancelling it only when it stops making progress.

    asyncio.wait_for is the bound, used as a progress check rather than a whole-item
    deadline: a healthy 15m deep backfill runs 40+ minutes across hundreds of rate-limited
    requests, so a fixed deadline would cancel good work. The item task is shielded so a
    check's timeout never cancels it; only a clock age at or past `stall_timeout_s` does.
    `on_tick` runs on every check (plan 04 feeds the systemd watchdog from it).
    """
    task = asyncio.ensure_future(make_coro())
    check_s = stall_timeout_s / _STALL_CHECKS_PER_TIMEOUT
    try:
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=check_s)
            except TimeoutError:
                if on_tick is not None:
                    on_tick()
                age = clock.age()
                if age >= stall_timeout_s:
                    task.cancel()
                    # Bounded: an item that swallows its cancellation must not hang us here.
                    await asyncio.wait({task}, timeout=check_s)
                    if not task.done():
                        logger.error("ibkr_history_fetcher.cancel_ignored", age_s=age)
                    raise ItemStalled(age) from None
    except asyncio.CancelledError:
        task.cancel()
        raise


@dataclass
class FetchContext:
    """Run-scoped state shared by every item of one fetcher run.

    The per-run caches replace what the pipeline's per-symbol loop got for free from
    iterating one symbol's timeframes together: a symbol is qualified once, its provider
    head is looked up at most once, and the FX/crypto 1m deep fetch runs at most once.
    """

    provider: Any
    settings: Any
    # Opens a fresh psycopg connection (autocommit, like the pipeline's connect_db).
    connect: Callable[[], Any]
    sink: Any
    fetch_run_id: str
    tf_fetch_config: Mapping[str, tuple[int, bool]]
    end_dt: datetime
    run_started_at: datetime
    empty_ranges: Mapping[tuple[str, str], Any]
    empty_reverify_days: int
    fresh_heads: dict[str, datetime]
    first_bars: Mapping[str, datetime]
    days_override: int | None = None
    per_contract: bool = False
    # Plan 185-22 (D-21): re-ask the last N 1d sessions so a split shows as a constant ratio.
    overlap_sessions: int = 0
    conn: Any = None
    qualified: dict[str, bool] = field(default_factory=dict)
    heads_checked: set[str] = field(default_factory=set)
    fx_derived: set[str] = field(default_factory=set)

    def get_conn(self) -> Any:
        """A live connection: the pipeline's SELECT 1 probe and reconnect, in one place."""
        if self.conn is not None:
            try:
                self.conn.cursor().execute("SELECT 1")
                return self.conn
            except Exception:
                try:
                    self.conn.close()
                except Exception:
                    pass
        self.conn = self.connect()
        return self.conn


def _bar_row(symbol: str, timeframe: str, bar: Any, *, archive: bool) -> tuple:
    """One bar as the destination writer's row: the grid 9-tuple, or the archive 10-tuple
    whose trailing base is NULL on fetched bars. Accepts an OHLCVBar or a bar dict."""
    get = bar.get if isinstance(bar, dict) else lambda key: getattr(bar, key)
    row = (
        get("timestamp"),
        symbol,
        timeframe,
        get("open"),
        get("high"),
        get("low"),
        get("close"),
        get("volume"),
        get("source"),
    )
    return row + (None,) if archive else row


class _ChunkPersister:
    """The on_chunk side of one timeframe's fetch (CD-04).

    Every provider chunk commits through persist_chunk_atomically with the request rows the
    provider reported for it (recorded before on_chunk, todo 462 order) and the series'
    CoverageDelta, so answer, bars and ledger land in one transaction. The pipeline did this
    for 15m/1h/5m only; 1m and the placeholder-path timeframes now join (1d persists nothing:
    its answers are D1 rows, plan 185-18 task 1b).
    """

    def __init__(
        self,
        ctx: FetchContext,
        symbol: str,
        timeframe: str,
        clock: ProgressClock,
        *,
        verify_overlap: bool = False,
        waived: bool = False,
    ):
        self.ctx = ctx
        self.symbol = symbol
        self.timeframe = timeframe
        self.clock = clock
        self.archive = timeframe in _ARCHIVE_TFS
        if waived and self.archive:
            raise ValueError(f"{symbol} {timeframe}: the revision waiver covers the grid only")
        self.verify_overlap = verify_overlap and not self.archive
        self.writer = (
            _insert_archive_rows
            if self.archive
            else (_insert_market_data_rows_waived if waived else _insert_market_data_rows)
        )
        self.request_ids: list[Any] = []
        self.persisted: set[datetime] = set()
        self.overlap_pairs: list[tuple[float, float]] = []
        self.n_rows = 0

    def on_request(self, record: Any) -> None:
        self.ctx.sink.on_request(record)
        self.request_ids.append(record.request_id)
        self.clock.touch()

    async def on_chunk(self, chunk_bars: list[Any]) -> None:
        self.persist(chunk_bars)

    def persist(self, bars: list[Any]) -> None:
        if not bars:
            return
        request_rows = self.ctx.sink.take_requests(list(self.request_ids))
        self.request_ids.clear()
        rows = [_bar_row(self.symbol, self.timeframe, b, archive=self.archive) for b in bars]
        conn = self.ctx.get_conn()
        if self.verify_overlap:
            fresh = {row[0]: row[6] for row in rows}
            stored = _stored_closes(conn, self.symbol, self.timeframe, sorted(fresh))
            self.overlap_pairs.extend(
                (float(stored[ts]), float(fresh[ts])) for ts in sorted(stored)
            )
        _, n_rows = persist_chunk_atomically(
            conn,
            request_rows=request_rows,
            archive_rows=rows,
            write_archive_rows=self.writer,
            coverage=CoverageDelta(
                self.symbol,
                self.timeframe,
                DESTINATION_ARCHIVE if self.archive else DESTINATION_GRID,
                fetched_at=datetime.now(UTC),
            ),
        )
        self.n_rows += n_rows
        self.persisted.update(row[0] for row in rows)
        self.clock.touch()


def _stored_closes(
    conn: Any, symbol: str, timeframe: str, timestamps: list[datetime]
) -> dict[datetime, float]:
    """Stored grid closes at `timestamps` (the ingress contract's own stored-row read)."""
    with conn.cursor() as cur:
        stored = read_stored(cur, DESTINATION_GRID, symbol, timeframe, timestamps)
    return {ts: values[3] for ts, values in stored.items()}


def _merge_windows(windows: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Sorted windows with overlapping or touching ones merged (end is the max end)."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _depth_days(ctx: FetchContext, timeframe: str) -> int:
    depth = ctx.tf_fetch_config[timeframe][0]
    return min(depth, ctx.days_override) if ctx.days_override else depth


def _needs_full_window(row: Any, *, full_scan: bool) -> bool:
    """Todo 387 and plan 189-10's two lanes: a series whose last fetch settled ok is asked
    from its latest bar forward (the update lane); a never-fetched or failed series, and a
    series on its gap-fill session (the caller's full_scan), plans its full depth window.
    A short start no longer forces the full window on every run: that is the gap-fill lane's
    cadence."""
    return full_scan or row.last_fetch_status != "ok" or row.latest_timestamp is None


def _midnight(ts: datetime) -> datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_qualified(ctx: FetchContext, instrument: Any) -> bool:
    """Qualify once per symbol per run. A disconnected client is reconnected first; if that
    fails the item is GatewayLost (not charged) and no verdict is cached (todo 051: a
    qualify on a dead socket returns False exactly like a genuine unknown contract)."""
    symbol = instrument.symbol
    if symbol in ctx.qualified:
        return ctx.qualified[symbol]
    if not ctx.provider.is_connected():
        logger.warning("ibkr_history_fetcher.reconnecting", symbol=symbol)
        if not await ctx.provider.connect():
            raise GatewayLost(f"IBKR reconnect before qualifying {symbol} failed")
    ctx.qualified[symbol] = bool(await ctx.provider.qualify_instrument(instrument))
    return ctx.qualified[symbol]


async def _head_floor(
    ctx: FetchContext, instrument: Any, timeframe: str, start_dt: datetime, *, tail: bool
) -> datetime | None:
    """The provider head snapped to midnight UTC, or None (migration 355).

    Looked up at most once per symbol per run, never for futures (the head is the named
    front month's, the long timeframes come from the continuous contract), never for a tail
    window, and only when this timeframe needs more than one chunk and stored history does
    not already reach the window start. A failed lookup applies no floor and is retried next
    run, never stored. Snapped to midnight: the head is the first trade's time, and a 1d bar
    is stamped 00:00, so flooring to the date skips less, never more.
    """
    symbol = instrument.symbol
    if instrument.asset_class == AssetClass.FUTURES:
        return None
    head_ts = ctx.fresh_heads.get(symbol)
    single_request = _depth_days(ctx, timeframe) <= ibkr._MAX_CHUNK_DAYS.get(timeframe, 0)
    first_bar = ctx.first_bars.get(symbol)
    if (
        head_ts is None
        and not tail
        and not single_request
        and symbol not in ctx.heads_checked
        and (first_bar is None or first_bar > start_dt)
    ):
        ctx.heads_checked.add(symbol)
        head_ts, head_error = await ctx.provider.get_head_timestamp(symbol)
        if head_ts is not None:
            empty_history.record_head(ctx.get_conn(), symbol, _EMPTY_HISTORY_PROVIDER, head_ts)
            ctx.fresh_heads[symbol] = head_ts
        else:
            logger.info("ibkr_history_fetcher.no_head", symbol=symbol, error=str(head_error))
    return _midnight(head_ts) if head_ts is not None else None


def _plan_gaps(
    ctx: FetchContext,
    instrument: Any,
    timeframe: str,
    start_dt: datetime,
    *,
    overlap: bool = False,
    refetch: bool = False,
) -> list[tuple[datetime, datetime]]:
    """The asks for one (symbol, timeframe), through the shared planners (plan 185-18).

    1d: D1 session coverage (detect_gaps_1d_from_d1), plus the optional overlap window.
    5m/15m/1h: the record planner (expected slots minus stored minus answered windows).
    Anything else (1m, 4h): the legacy grid difference with the empty-history gate.
    Every path folds in the provider-verified empty span under one freshness rule.

    Plan 189-10: `overlap` adds [start_dt, end) to a record-planned series (the update lane
    re-asks stored slots behind its latest bar; the planner never asks a stored slot).
    `refetch` (the escalation after a restated overlap) asks the whole window, stored or not:
    every 1d session of it, every record-planned slot of it.
    """
    symbol, end_dt = instrument.symbol, ctx.end_dt
    empty = ctx.empty_ranges.get((symbol, timeframe))

    def note_skip(skipped: Any) -> None:
        logger.info(
            "ibkr_history_fetcher.empty_history_skipped",
            symbol=symbol,
            timeframe=timeframe,
            empty_from=str(skipped.empty_from.date()),
            empty_through=str(skipped.empty_through.date()),
        )

    gate: dict[str, Any] = dict(
        empty=empty,
        now=ctx.run_started_at,
        reverify_days=ctx.empty_reverify_days,
        min_confirmations=ibkr._NO_DATA_CONFIRMATION_CHUNKS,
        on_skip=note_skip,
    )
    if timeframe == "1d":
        # 1d planning is defined on the NYSE session grid; a non-NYSE name would get NYSE
        # holidays planned as permanent holes, so refuse loudly until a second calendar exists.
        if getattr(instrument, "session_id", "nyse") != "nyse":
            raise ValueError(
                f"1d gap planning is NYSE-only; {symbol} has session_id={instrument.session_id!r}"
            )
        gaps_d = detect_gaps_1d_from_d1(
            ctx.get_conn(),
            symbol,
            start_dt.date(),
            end_dt.date(),
            nyse_sessions(start_dt.date(), end_dt.date()),
            **gate,
        )
        if refetch:
            window = nyse_sessions(start_dt.date(), end_dt.date())
            gaps_d = with_overlap_window(gaps_d, window, end_dt.date(), len(window))
        elif ctx.overlap_sessions > 0:
            # Sessions back from end, with calendar slack for weekends and holidays.
            overlap_days = int(ctx.overlap_sessions * 1.6) + 10
            gaps_d = with_overlap_window(
                gaps_d,
                nyse_sessions(end_dt.date() - timedelta(days=overlap_days), end_dt.date()),
                end_dt.date(),
                ctx.overlap_sessions,
            )
        return [(midnight_utc(s), midnight_utc(e)) for s, e in gaps_d]
    if timeframe in _RECORD_PLAN_TFS:
        planned = detect_gaps_from_record(
            ctx.get_conn(),
            symbol,
            timeframe,
            start_dt,
            end_dt,
            expected_grid_slots(
                instrument.session_id, instrument.exchange, timeframe, start_dt, end_dt
            ),
            **gate,
        )
        if refetch or overlap:
            return _merge_windows([*planned, (start_dt, end_dt)])
        return planned
    conn = ctx.get_conn()
    gaps = detect_gaps(
        conn,
        symbol,
        timeframe,
        start_dt,
        end_dt,
        session_id=instrument.session_id,
        exchange=instrument.exchange,
        # Real-bars-only (1m): the answered windows are all that keeps a definitive
        # no_data span from being re-asked forever (todo 462).
        answered=(
            load_answered_windows(conn, symbol, timeframe)
            if real_bars_only_for(timeframe)
            else None
        ),
    )
    kept = empty_history.apply_empty_range(
        gaps,
        empty,
        ctx.run_started_at,
        ctx.empty_reverify_days,
        timedelta(minutes=_TF_MINUTES[timeframe]),
        ibkr._NO_DATA_CONFIRMATION_CHUNKS,
    )
    if kept != gaps and empty is not None:
        note_skip(empty)
    return kept


async def fetch_item(
    ctx: FetchContext,
    instrument: Any,
    row: Any,
    *,
    full_scan: bool,
    clock: ProgressClock,
    overlap_days: int = 0,
    refetch: bool = False,
    waived: bool = False,
) -> ItemOutcome:
    """Fetch one (symbol, timeframe) with the pipeline loop body's rules (CD-01/04/05).

    Plan 189-10's lanes (the fetcher decides them per item): the update lane asks a covered
    series from its latest bar, `overlap_days` earlier for a grid series, and reports the
    overlap's (stored, fresh) closes in overlap_pairs; full_scan plans the full depth (the
    gap-fill lane); refetch re-asks the whole depth including stored history (the
    escalation), through the waived grid writer when `waived` (a recorded corporate action).

    Ported from the historical pipeline script's main()._run_fetch_stage as it
    stands after plans 185-18 (shared gap planner, D1-only 1d), 185-19 (1d empty history
    reconciled from D1) and 185-22 (1d overlap). Changes versus the pipeline:
    - CD-04: every non-1d chunk persists atomically with its requests and CoverageDelta.
    - Todo 387: a fully covered series is planned from its latest bar, not 20 years back.
    - CD-05: the outcome is classified (ok / no_data / error) for the ledger.
    - CD-08: the clock is touched on every answered request and persisted chunk.
    - The head lookup, qualify and FX/crypto 1m deep fetch are cached per symbol per run.

    A 1d item stores no bar (D2 owns the 1d grid). When it delivered bars it returns
    derive_1d_since; the caller runs the daily derivation stage for those symbols, as the
    pipeline did after its loop.

    Raises GatewayLost when the client is down and cannot be reconnected, and lets a sink
    flush failure raise (phase 185 D-05: raw answers are never dropped silently);
    fetch_item_with_retries turns both into outcomes.
    """
    symbol, timeframe = instrument.symbol, row.timeframe
    clock.touch()

    if not await _ensure_qualified(ctx, instrument):
        return ItemOutcome(symbol, timeframe, "error", error=f"{symbol}: qualify failed")

    use_continuous = ctx.tf_fetch_config[timeframe][1]
    fetch_days = _depth_days(ctx, timeframe)
    is_futures = instrument.asset_class == AssetClass.FUTURES

    if ctx.per_contract and is_futures:
        n_bars, _ = await fetch_per_contract(
            provider=ctx.provider,
            instrument=instrument,
            timeframe=timeframe,
            fetch_days=fetch_days,
            end_dt=ctx.end_dt,
            db_conn=ctx.get_conn(),
        )
        clock.touch()
        # fetch_per_contract prints and swallows per-contract errors, so zero stored bars
        # cannot be told apart from a failure: charged as an error, never as no_data.
        status = "ok" if n_bars > 0 else "error"
        error = None if n_bars > 0 else "per-contract fetch stored no bars"
        return ItemOutcome(symbol, timeframe, status, n_bars=n_bars, error=error)

    start_dt = _fetch_start(ctx.end_dt, fetch_days)
    tail = not refetch and not _needs_full_window(row, full_scan=full_scan)
    overlap = tail and overlap_days > 0 and timeframe in _RECORD_PLAN_TFS
    if tail:
        tail_start = _midnight(row.latest_timestamp)
        if overlap:
            tail_start -= timedelta(days=overlap_days)
        start_dt = max(start_dt, tail_start)
    head_floor = await _head_floor(ctx, instrument, timeframe, start_dt, tail=tail)
    if head_floor is not None and head_floor > start_dt:
        start_dt = head_floor

    gaps = _plan_gaps(ctx, instrument, timeframe, start_dt, overlap=overlap, refetch=refetch)
    clock.touch()
    if not gaps:
        return ItemOutcome(symbol, timeframe, "ok")

    windows = cluster_gap_ranges(gaps, max_gap_days=_history_fetch._GAP_CLUSTER_MAX_DAYS)
    d1_capture = timeframe == "1d"
    interval = timedelta(minutes=_TF_MINUTES[timeframe])
    use_cont = use_continuous and fetch_days > 14 and is_futures
    persister = _ChunkPersister(
        ctx, symbol, timeframe, clock, verify_overlap=overlap, waived=waived and not d1_capture
    )
    capture = _capture_kwargs(timeframe, ctx.sink, ctx.fetch_run_id)
    if d1_capture:
        base_on_request = capture["on_request"]

        def on_request_1d(record: Any) -> None:
            base_on_request(record)
            clock.touch()

        capture["on_request"] = on_request_1d
    else:
        capture["on_request"] = persister.on_request

    n_returned = 0
    failed: list[str] = []
    reconcile_1d = False
    for gap_start, gap_end in windows:
        # Only the oldest window can be pre-history; its walk's definitive no-data answers
        # are what ohlcv_empty_history records.
        observed: list[EmptyHistory] = []
        is_oldest = (gap_start, gap_end) == windows[0]
        # The record and D1 planners are end-exclusive (gap_end is the last missing slot's
        # end); the legacy planner's 1m range ends at the slot's start, so 1m asks through
        # the slot's end, capped at now so a bar still forming stays a gap.
        fetch_end = min(gap_end + interval, ctx.end_dt) if timeframe == "1m" else gap_end
        try:
            bars = await ctx.provider.fetch_historical_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=gap_start,
                end=fetch_end,
                continuous=use_cont,
                on_chunk=None if d1_capture else persister.on_chunk,
                on_empty_history=observed.append if is_oldest else None,
                **capture,
            )
            # A chunk that failed every retry does not raise; the window is incomplete.
            n_failed_chunks = getattr(ctx.provider, "last_fetch_failed_chunks", 0)
            if n_failed_chunks:
                failed.append(f"{gap_start.date()}-{gap_end.date()}: {n_failed_chunks} chunk(s)")
            n_returned += len(bars)
            if not d1_capture:
                # Defensive: the provider hands every chunk to on_chunk, but a returned bar
                # that missed it must still land with its coverage, never be dropped.
                persister.persist([b for b in bars if b.timestamp not in persister.persisted])
            if is_oldest and not use_cont:
                if d1_capture:
                    # Plan 185-19: 1d empty history is derived from the recorded answers
                    # after the flush, not from the in-memory walk.
                    reconcile_1d = True
                else:
                    empty_history.reconcile(
                        ctx.get_conn(),
                        symbol,
                        timeframe,
                        _EMPTY_HISTORY_PROVIDER,
                        (gap_start, gap_end),
                        observed[-1] if observed else None,
                        ctx.empty_ranges.get((symbol, timeframe)),
                        # chunk boundaries sit a day apart
                        timedelta(days=1) + interval,
                    )
        except Exception as error:
            failed.append(f"{gap_start.date()}-{gap_end.date()}: {error}")
            logger.error(
                "ibkr_history_fetcher.window_failed",
                symbol=symbol,
                timeframe=timeframe,
                window_start=str(gap_start.date()),
                window_end=str(gap_end.date()),
                error=str(error),
            )

    n_bars = n_returned if d1_capture else persister.n_rows
    if (
        not d1_capture
        and n_bars == 0
        and instrument.asset_class in (AssetClass.FX, AssetClass.CRYPTO)
        and timeframe in _FX_DERIVED_TFS
    ):
        try:
            n_bars = await _fx_derive(ctx, instrument, timeframe, clock)
        except Exception as error:
            failed.append(f"1m derivation: {error}")
            logger.error(
                "ibkr_history_fetcher.fx_derivation_failed",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
            )

    # D1 flush once per item (phase 185 D-05): a failure raises, the item fails loudly.
    _flush_capture(ctx.sink, ctx.settings)
    if reconcile_1d:
        empty_history.reconcile_empty_history(
            ctx.get_conn(), "1d", _EMPTY_HISTORY_PROVIDER, symbols=[symbol]
        )

    failure = "; ".join(failed) if failed else None
    status = "error" if failed else ("ok" if n_bars > 0 else "no_data")
    return ItemOutcome(
        symbol,
        timeframe,
        status,
        n_bars=n_bars,
        n_grid_source_rows=n_bars if timeframe == _GRID_SOURCE_TF else 0,
        error=failure,
        derive_1d_since=start_dt if d1_capture and n_returned > 0 else None,
        overlap_pairs=tuple(persister.overlap_pairs),
    )


async def _fx_derive(
    ctx: FetchContext, instrument: Any, timeframe: str, clock: ProgressClock
) -> int:
    """FX/crypto fallback: derive `timeframe` from 1m when its direct fetch stored nothing.

    Kept from the pipeline for asset_agnostic (no FX/crypto name is active today). The deep
    1m fetch runs once per symbol per run; its chunks and every derived timeframe's rows
    persist atomically with their coverage. The pipeline derived every missing timeframe at
    once after the symbol's loop; per item, each missing timeframe derives from the stored 1m.
    Returns the derived rows persisted.
    """
    symbol = instrument.symbol
    if symbol not in ctx.fx_derived:
        ctx.fx_derived.add(symbol)
        deep_days = _1M_DAYS_FX if instrument.asset_class == AssetClass.FX else _1M_DAYS_CRYPTO
        deep_start = _midnight(ctx.end_dt - timedelta(days=deep_days))
        deep = _ChunkPersister(ctx, symbol, _FX_SOURCE_TF, clock)
        capture = dict(
            _capture_kwargs(_FX_SOURCE_TF, ctx.sink, ctx.fetch_run_id),
            on_request=deep.on_request,
        )
        bars = await ctx.provider.fetch_historical_bars(
            symbol=symbol,
            timeframe=_FX_SOURCE_TF,
            start=deep_start,
            end=ctx.end_dt,
            continuous=False,
            on_chunk=deep.on_chunk,
            **capture,
        )
        deep.persist([b for b in bars if b.timestamp not in deep.persisted])
        if getattr(ctx.provider, "last_fetch_failed_chunks", 0):
            raise RuntimeError(f"{symbol}/1m deep fetch: chunks failed every retry")
    bars_1m = fetch_bars(ctx.get_conn(), symbol, _FX_SOURCE_TF)
    if not bars_1m:
        return 0
    derived = _ChunkPersister(ctx, symbol, timeframe, clock)
    derived.persist(aggregate_bars_from_1m(bars_1m, timeframe))
    return derived.n_rows


async def fetch_item_with_retries(
    ctx: Any,
    instrument: Any,
    row: Any,
    *,
    full_scan: bool,
    config: Any,
    reconnect: Callable[[], Awaitable[bool]],
    on_tick: Callable[[], None] | None = None,
    overlap_days: int = 0,
    refetch: bool = False,
    waived: bool = False,
) -> ItemOutcome:
    """fetch_item under the stall bound, retried after a stall at most
    config.history_request_retries times (CD-08).

    - A stall cancels the attempt, flushes the D1 sink (the cancelled attempt's answered
      requests and observations are raw answers that must not be dropped; its persisted
      chunks are already committed atomically), disconnects and reconnects the client. A
      failed reconnect ends the item as gateway_lost, which the caller does not charge.
    - Stalling on every attempt is 'error', a genuine consecutive failure. The client is
      reconnected after the last stall too, so the next item starts on a live connection.
    - Any other exception ends the item as 'error' with its message, logged once, never a
      crash: one name never blocks the run (phase 185 D-05).
    """
    started = time.monotonic()
    symbol, timeframe = row.symbol, row.timeframe
    max_attempts = 1 + config.history_request_retries

    def ended(status: str, attempt: int, **fields: Any) -> ItemOutcome:
        return ItemOutcome(
            symbol,
            timeframe,
            status,
            attempts=attempt,
            elapsed_s=time.monotonic() - started,
            **fields,
        )

    last_stall: ItemStalled | None = None
    for attempt in range(1, max_attempts + 1):
        clock = ProgressClock()

        def attempt_coro(_clock: ProgressClock = clock) -> Awaitable[ItemOutcome]:
            return fetch_item(
                ctx,
                instrument,
                row,
                full_scan=full_scan,
                clock=_clock,
                overlap_days=overlap_days,
                refetch=refetch,
                waived=waived,
            )

        try:
            outcome: ItemOutcome = await run_with_stall_bound(
                attempt_coro,
                stall_timeout_s=config.history_request_timeout_s,
                clock=clock,
                on_tick=on_tick,
            )
        except ItemStalled as stall:
            last_stall = stall
            logger.warning(
                "ibkr_history_fetcher.item_stalled",
                symbol=symbol,
                timeframe=timeframe,
                attempt=attempt,
                elapsed_s=round(stall.elapsed_s, 1),
            )
            flush_error = _flush_after_cancel(ctx)
            if not await _reconnect(ctx, reconnect):
                return ended(
                    "error", attempt, gateway_lost=True, error=f"reconnect failed: {stall}"
                )
            if flush_error is not None:
                return ended(
                    "error", attempt, error=f"sink flush after stall failed: {flush_error}"
                )
            continue
        except GatewayLost as error:
            logger.warning(
                "ibkr_history_fetcher.gateway_lost",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
            )
            return ended("error", attempt, gateway_lost=True, error=str(error))
        except Exception as error:
            logger.error(
                "ibkr_history_fetcher.item_failed",
                symbol=symbol,
                timeframe=timeframe,
                attempt=attempt,
                error=str(error),
                error_type=type(error).__name__,
            )
            return ended("error", attempt, error=f"{type(error).__name__}: {error}")
        return replace(outcome, attempts=attempt, elapsed_s=time.monotonic() - started)
    return ended(
        "error", max_attempts, error=f"stalled on all {max_attempts} attempts: {last_stall}"
    )


def _flush_after_cancel(ctx: Any) -> Exception | None:
    """Write what the cancelled attempt captured but had not yet flushed. Returns the error
    instead of raising so the client is still reconnected for the next item."""
    try:
        _flush_capture(ctx.sink, ctx.settings)
    except Exception as error:
        logger.error("ibkr_history_fetcher.stall_flush_failed", error=str(error))
        return error
    return None


async def _reconnect(ctx: Any, reconnect: Callable[[], Awaitable[bool]]) -> bool:
    try:
        await ctx.provider.disconnect()
    except Exception as error:  # a dead socket may refuse a clean disconnect
        logger.warning("ibkr_history_fetcher.disconnect_failed", error=str(error))
    try:
        return bool(await reconnect())
    except Exception as error:
        logger.error("ibkr_history_fetcher.reconnect_failed", error=str(error))
        return False
