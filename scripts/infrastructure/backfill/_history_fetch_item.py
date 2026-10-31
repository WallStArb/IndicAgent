"""One IBKR history queue item: fetch a (symbol, timeframe), bounded against hangs
(phase 189 plan 03; design docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md).

The IBKR history fetcher works its priority queue one (symbol, timeframe) at a time. This
module is that unit of work, moved out of the historical pipeline's monolithic per-symbol
loop (the historical pipeline script's main()._run_fetch_stage, now _history_fetch.py's
helpers) so it can be tested alone and so a single name can never hold the run:

- CD-01: one fetcher, one item at a time; the queue decides order, this module decides how
  one item is fetched.
- CD-04: every provider-returned chunk (1m, 5m, 15m, 1h and the daily answers) commits through
  _intraday_persist.persist_chunk_atomically into ohlcv_raw, together with its request rows and
  its ohlcv_coverage update, so the ledger never describes bars that did not land and no
  answered request outruns its bars. Raw is stored per source, agnostic to every other source:
  the item never asks what another vendor holds. The one refusal left is a vendor restating
  its OWN stored raw rows beyond the threshold, which fails the item (phase 191 plan 05).
- CD-05: the outcome is classified so the ledger only charges genuine failures. A correct
  empty answer is 'no_data', never 'error'; a lost gateway is not the item's fault at all.
- CD-08: a progress-aware stall bound cancels an item whose provider went silent, reconnects
  the client and retries a bounded number of times. ibkr.py's own per-request wait_for has been
  seen not to fire (2026-07-05 and 2026-10-02 incidents), so this is the in-process layer; the
  systemd WatchdogSec of plan 04 covers the case where asyncio timers never fire at all.

The fetch helpers (gap detection, store paths, per-contract futures, 1m derivation, D1
capture) live in _history_fetch.py, the CLI-free helper library plan 189-08 made of the
historical pipeline. Every timeframe stores real provider bars only (plan 185-32), so no
item writes a placeholder, a derived bar or fetch bookkeeping. All provider access goes through IBKRProvider methods;
src/providers/ibkr.py stays the only ib_async importer.

Phase 190 (provider history plane unification): this module IS the ibkr registry entry's
fetch-hook implementation (ohlcv_history_fetcher._ibkr_entry_fetch drives it). Everything
here is ibkr-entry-path-only by construction -- qualification (_ensure_qualified), the
provider head floor with its futures branch, the FX/crypto 1m derive, venue fallback and
the what_to_show/route request capture are IBKR request mechanics, fenced behind the one
registry entry. No NEW vendor branches belong in this module: anything the vendor-blind
loop needs to know about a vendor arrives as data, through the item's ProviderPlan
(ctx.plan: request budgets, no-data confirmation threshold, inter-item pacing) or through
the leaf itself. Chunk sizing stays the leaf module's own native data (ibkr._MAX_CHUNK_DAYS
and its APR overlay).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
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
from scripts.infrastructure.backfill._fetch_queue import ProviderPlan
from scripts.infrastructure.backfill._history_fetch import (
    _RECORD_PLAN_TFS,
    _TF_MINUTES,
    _capture_kwargs,
    _fetch_start,
    _flush_capture,
    cluster_gap_ranges,
    detect_gaps,
    fetch_per_contract,
)
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.complete_bar_gate import keep_complete
from services.ohlcv_coverage_writer import DESTINATION_RAW, FETCH_STATUSES, CoverageDelta
from services.ohlcv_raw_writer import RawRow, read_stored_closes
from src.core.models import AssetClass
from src.intelligence.bars.gap_plan import expected_grid_slots
from src.intelligence.bars.sessions import nyse_sessions, session_complete_at
from src.intelligence.bars.vendor_kind import (
    VENDOR_IBKR,
    UnmappedObservation,
    label_to_vendor_kind,
    observation_kind,
)
from src.providers import ibkr
from src.providers.base import EmptyHistory, HistoryProvider

logger = structlog.get_logger(__name__)

# The 5m grid is the source the 15m/1h grid is derived from (services/bar_derivation.py).
_GRID_SOURCE_TF = "5m"

# The stall bound is checked this many times per stall_timeout_s. Derived check cadence, not a
# tunable: the bound itself is infra.ibkr.history_request_timeout (APR); three checks per
# bound cap how far past it a stall can run before cancellation at a third of the bound.
_STALL_CHECKS_PER_TIMEOUT = 3


@dataclass(frozen=True)
class ItemOutcome:
    """How one queue item ended. The fetcher writes `status` to ohlcv_coverage through
    record_fetch_outcome (provider-labeled, phase 190) unless `gateway_lost` is set (a
    lost gateway is not charged)."""

    symbol: str
    timeframe: str
    status: str
    # The planning plane that fetched the item, stamped by the ibkr registry entry's
    # fetch path (phase 190 plan 04); the loop treats it as data.
    provider: str = "ibkr"
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
    # Restatements the detector flagged this item (written last-wins all the same, D-191-N).
    flags: tuple[str, ...] = ()
    # Of those, series flagged with a basis-change signature (a common price or volume
    # multiple, a time shift): the run is partial until each is reviewed (fourth review of
    # 191-07, finding 2; scripts/ops/bars/ops_restatement_review.py).
    n_basis_flagged: int = 0
    # Slots this item put in raw that no ranked vendor selects (D-191-L rule 4): the rows are
    # in raw, canonical has none for them. The run is partial while any exist (191-07 review).
    n_unselected: int = 0
    # 1d requests whose route or what_to_show has no raw kind (review finding 11): not stored,
    # the rest of the window is; the item ends error with an `unmapped_kind:` message.
    unmapped: tuple[str, ...] = ()
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

    provider: HistoryProvider
    settings: Any
    # Opens a fresh psycopg connection (autocommit, like the pipeline's connect_db).
    connect: Callable[[], Any]
    sink: Any
    fetch_run_id: str
    tf_fetch_config: Mapping[str, tuple[int, bool]]
    end_dt: datetime
    run_started_at: datetime
    # Run-level provider state, keyed (vendor, symbol, timeframe) so one shared context serves
    # every vendor of the run and an item reads only its own vendor's records (raw is per
    # source). empty_ranges: recorded pre-history spans; fresh_heads: verified provider heads;
    # tape_floors: seeded one-direction floors (nothing exists before them, they are not heads);
    # first_bars: the vendor's oldest own raw bar, read lazily by _head_floor and cached here.
    empty_ranges: Mapping[tuple[str, str, str], Any]
    empty_reverify_days: int
    fresh_heads: dict[tuple[str, str, str], datetime]
    first_bars: dict[tuple[str, str, str], datetime]
    tape_floors: Mapping[tuple[str, str, str], datetime] = field(default_factory=dict)
    days_override: int | None = None
    per_contract: bool = False
    # Plan 185-22 (D-21): re-ask the last N 1d sessions so a split shows as a constant ratio.
    overlap_sessions: int = 0
    # The item's ProviderPlan (phase 190 plan 04), carried in by the ibkr registry entry's
    # fetch hook: vendor semantics (request budgets, the no-data confirmation threshold)
    # read from the plan, never from module constants.
    plan: ProviderPlan | None = None
    conn: Any = None
    qualified: dict[str, bool] = field(default_factory=dict)
    # (vendor, symbol) -> the head lookup's answer this run (None: the lookup failed); one
    # provider call per symbol serves every timeframe's head row.
    first_bars_checked: set[tuple[str, str, str]] = field(default_factory=set)
    head_lookups: dict[tuple[str, str], datetime | None] = field(default_factory=dict)
    # APR threshold.bar_integrity.session_close_settle_s (migration 479): a bar ending at or
    # after its session close is a complete answer only this long after the close. Loaded by
    # the fetcher at context build; None refuses to persist (a silent zero would keep partials).
    settle: timedelta | None = None

    @property
    def vendor(self) -> str:
        """The source this run fetches for: every plan read and coverage row is scoped to it
        (raw is stored per source). It is the item plan's provider name, data not a branch;
        a context built without a plan is the IBKR fetcher's own."""
        return self.plan.name if self.plan is not None else VENDOR_IBKR

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


def _raw_rows(symbol: str, timeframe: str, bars: list[Any], record: Any | None) -> list[RawRow]:
    """Provider bars as RawRow. Accepts an OHLCVBar or a bar dict.

    Vendor and kind are what the vendor served. A daily answer's kind comes from the request that
    carried it (route and what_to_show through vendor_kind.observation_kind: smart_trades,
    smart_adjusted or one venue_<route> kind; an unmapped pair raises). An intraday chunk's kind
    comes from the bar's source label (ibkr_named is (ibkr, named)), so 15m and 1h are ordinary
    raw rows with no separate path.
    """
    daily_request: tuple[str, str] | None = None
    if timeframe == "1d":
        if record is None:
            raise ValueError(f"{symbol} 1d bars reach the persister without their request record")
        daily_request = (record.route, record.what_to_show)
    rows = []
    for bar in bars:

        def get(key: str, _bar: Any = bar) -> Any:
            return _bar[key] if isinstance(_bar, dict) else getattr(_bar, key)

        vendor, kind = label_to_vendor_kind(get("source"))
        if daily_request is not None:
            kind = observation_kind(vendor, *daily_request)
        volume = get("volume")
        rows.append(
            RawRow(
                timestamp=get("timestamp"),
                symbol=symbol,
                timeframe=timeframe,
                vendor=vendor,
                kind=kind,
                open=get("open"),
                high=get("high"),
                low=get("low"),
                close=get("close"),
                volume=None if volume is None else int(volume),
            )
        )
    return rows


class _ChunkPersister:
    """The persist side of one timeframe's fetch (CD-04).

    Every answered request's bars arrive through on_observation together with the request's
    record (reported first through on_request, todo 462 order) and commit through
    persist_chunk_atomically with that request row and, intraday, the series' CoverageDelta, so
    answer, bars and ledger land in one transaction. A daily answer's raw kind comes from the
    request's route and what_to_show; it carries no coverage update (the daily derivation stage
    refreshes the 1d bounds). 15m and 1h are ordinary raw rows.

    Complete bars only (second review of 191-07, finding 5): before anything is offered, the
    answer is split by src/intelligence/bars/complete_bars.py against the request's own
    answered_at and window end, every vendor alike. A bar that straddles the request end, was
    still forming when the vendor answered, or closes the session and was answered before the
    settle delay is not this source's answer: it is written onto the request row
    (`ohlcv_request.partial_bars`), logged with its values, and not offered to raw; the gap
    planner keeps its slot a gap. 1d keeps D-191-J (complete at the session close).

    Every chunk is written last-wins (D-191-N): a vendor restating its OWN stored raw rows
    overwrites them and the old values are logged as revisions. A restatement the detector
    flags (share or basis-change signature) is kept in `flags` and reported on the outcome; it
    never stops the walk or fails the item, and a basis-change flag makes the run partial. A difference from another vendor is a different key
    and never reaches the detector. `waived` no longer changes the write; the escalation path
    still passes it for its log.
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
        self.daily = timeframe == "1d"
        self.verify_overlap = verify_overlap
        self.waived = waived
        self.request_ids: list[Any] = []
        self.persisted: set[datetime] = set()
        self.overlap_pairs: list[tuple[float, float]] = []
        self.n_rows = 0
        self.flags: list[str] = []
        self.n_basis_flagged = 0
        self.n_unselected = 0
        self.unmapped: list[str] = []
        # Every stamp an answer handed in, complete or not: the item's defensive re-offer of
        # returned bars skips them (a held-back partial must not slip in without its record).
        self.answered: set[datetime] = set()
        self.n_partial = 0

    def on_request(self, record: Any) -> None:
        self.ctx.sink.on_request(record)
        self.request_ids.append(record.request_id)
        self.clock.touch()

    def on_observation(self, record: Any, bars: list[Any]) -> None:
        """One request's answer (the provider calls this synchronously after on_request)."""
        self.persist(
            bars,
            record=record,
            answered_at=record.answered_at,
            request_end=None if self.daily else record.window_end,
        )

    def persist(
        self,
        bars: list[Any],
        *,
        answered_at: datetime,
        request_end: datetime | None,
        record: Any | None = None,
    ) -> None:
        """Offer an answer's complete bars. `answered_at` is the answer time (a lower bound
        when no record carries it); `request_end` the request's end (None for 1d)."""
        if self.ctx.settle is None:
            raise RuntimeError("FetchContext.settle is not loaded (APR session_close_settle_s)")
        self.answered.update(b["timestamp"] if isinstance(b, dict) else b.timestamp for b in bars)
        bars, partial, partial_text = keep_complete(
            bars,
            self.timeframe,
            answered_at=answered_at,
            request_end=request_end,
            settle=self.ctx.settle,
            symbol=self.symbol,
            caller="ibkr_history_fetcher",
        )
        if partial:
            # D-191-J and its intraday analogue: raw is last-wins, so offering the partial would
            # log the completed bar as a restatement later. The request row stays buffered with
            # the partial values on it; the planner keeps the slot a gap.
            self.n_partial += len(partial)
            if record is not None:
                self.ctx.sink.note_partial(record.request_id, partial_text)
        if not bars:
            return
        request_rows = self.ctx.sink.take_requests(list(self.request_ids))
        self.request_ids.clear()
        try:
            rows = _raw_rows(self.symbol, self.timeframe, bars, record)
        except UnmappedObservation as error:
            # The request row stays buffered for the ledger; the walk goes on.
            self.unmapped.append(str(error))
            logger.error(
                "ibkr_history_fetcher.unmapped_kind",
                symbol=self.symbol,
                timeframe=self.timeframe,
                error=str(error),
            )
            return
        conn = self.ctx.get_conn()
        if self.verify_overlap:
            self.overlap_pairs.extend(_overlap_pairs(conn, self.symbol, self.timeframe, rows))
        result = persist_chunk_atomically(
            conn,
            request_rows=request_rows,
            raw_rows=rows,
            coverage=(
                None
                if self.daily
                else CoverageDelta(
                    self.symbol,
                    self.timeframe,
                    DESTINATION_RAW,
                    fetched_at=datetime.now(UTC),
                    provider=self.ctx.vendor,
                )
            ),
            request_id=uuid.UUID(str(record.request_id)) if record is not None else None,
            answered_at=answered_at,
            refresh_1d_provider=self.ctx.vendor if self.daily else None,
        )
        ingress = result.ingress
        if ingress is not None and ingress.flagged:
            stamps = [row.timestamp for row in rows]
            for flag in ingress.flagged:
                self.flags.append(
                    f"{min(stamps).date()}-{max(stamps).date()}: {flag.restatement.detail()}"
                )
            self.n_basis_flagged += ingress.n_basis_flagged
        self.n_rows += result.n_rows
        if ingress is not None and ingress.n_unselected:
            self.n_unselected += ingress.n_unselected
            logger.error(
                "ibkr_history_fetcher.chunk_unselected",
                symbol=self.symbol,
                timeframe=self.timeframe,
                n_unselected=ingress.n_unselected,
            )
        self.persisted.update(row.timestamp for row in rows)
        self.clock.touch()


def _overlap_pairs(
    conn: Any, symbol: str, timeframe: str, rows: list[RawRow]
) -> list[tuple[float, float]]:
    """(stored close, fresh close) for every fresh row whose slot the SAME source already stores
    in raw, read before the write (the update lane's overlap judgment). Another vendor's row at
    the slot is not an overlap."""
    fresh: dict[tuple[str, str], dict[datetime, float]] = {}
    for row in rows:
        fresh.setdefault((row.vendor, row.kind), {})[row.timestamp] = row.close
    pairs: list[tuple[float, float]] = []
    for (vendor, kind), closes in sorted(fresh.items()):
        stored = read_stored_closes(conn, symbol, timeframe, vendor, kind, closes)
        pairs.extend((float(stored[ts]), float(closes[ts])) for ts in sorted(stored))
    return pairs


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


def _vendor_first_bar(
    ctx: FetchContext, vendor: str, symbol: str, timeframe: str
) -> datetime | None:
    """The vendor's oldest own raw bar for the series, read once per run and cached."""
    key = (vendor, symbol, timeframe)
    if key not in ctx.first_bars and key not in ctx.first_bars_checked:
        ctx.first_bars_checked.add(key)
        found = empty_history.load_first_bar(ctx.get_conn(), symbol, timeframe, vendor)
        if found is not None:
            ctx.first_bars[key] = found
    return ctx.first_bars.get(key)


async def _head_floor(
    ctx: FetchContext, instrument: Any, timeframe: str, start_dt: datetime, *, tail: bool
) -> datetime | None:
    """The earliest instant worth asking for this series, snapped to midnight UTC, or None.

    A verified provider head (migration 355/465, one row per symbol and timeframe) wins; with
    none, the lookup runs when this timeframe needs more than one chunk and the vendor's own
    stored history does not already reach the window start, and its answer is recorded for
    the timeframe. A seeded tape floor is only the fallback bound when no head is known: it
    says nothing exists before it, never where the symbol's history begins. Never for futures
    (the head is the named front month's, the long timeframes come from the continuous
    contract), never for a tail window. One provider lookup per symbol per run serves every
    timeframe. A failed lookup is not stored and is retried next run. Snapped to midnight: the
    head is the first trade's time and a 1d bar is stamped 00:00, so flooring to the date
    skips less, never more.
    """
    symbol = instrument.symbol
    if instrument.asset_class == AssetClass.FUTURES:
        return None
    vendor = ctx.vendor
    key = (vendor, symbol, timeframe)
    head_ts = ctx.fresh_heads.get(key)
    single_request = _depth_days(ctx, timeframe) <= ibkr._MAX_CHUNK_DAYS.get(timeframe, 0)
    if head_ts is None and not tail and not single_request:
        first_bar = _vendor_first_bar(ctx, vendor, symbol, timeframe)
        needs_head = first_bar is None or first_bar > start_dt
    else:
        needs_head = False
    if needs_head:
        lookup_key = (vendor, symbol)
        if lookup_key not in ctx.head_lookups:
            head_ts, head_error = await ctx.provider.get_head_timestamp(symbol)
            ctx.head_lookups[lookup_key] = head_ts
            if head_ts is None:
                logger.info("ibkr_history_fetcher.no_head", symbol=symbol, error=str(head_error))
        head_ts = ctx.head_lookups[lookup_key]
        if head_ts is not None:
            empty_history.record_head_per_tf(ctx.get_conn(), symbol, vendor, timeframe, head_ts)
            ctx.fresh_heads[key] = head_ts
    if head_ts is None:
        head_ts = ctx.tape_floors.get(key)
    return _midnight(head_ts) if head_ts is not None else None


def _before_head(window_end: datetime, head_floor: datetime | None) -> bool:
    """True when the whole window lies at or before the vendor's head (or tape floor)."""
    return head_floor is not None and window_end <= head_floor


def _plan_gaps(
    ctx: FetchContext, instrument: Any, timeframe: str, start_dt: datetime
) -> list[tuple[datetime, datetime]]:
    """The gap asks for one (symbol, timeframe) of ctx.vendor, through the shared planners.

    Raw is stored per source, agnostic to every other source, so the one question is: which
    slots of [start_dt, end) are missing from THIS vendor's own ohlcv_raw rows, minus its own
    answered request windows (a confirmed empty included)? Another vendor's rows, answers and
    the canonical selection never cover a slot. No date cutoff restricts the question.

    1d: the vendor's complete daily bars per NYSE session (detect_gaps_1d_from_d1).
    5m/15m/1h: the record planner (expected slots minus stored minus answered windows).
    Anything else (1m, 4h): the legacy grid difference with the empty-history gate.
    Every path folds in the provider-verified empty span under one freshness rule.
    """
    symbol, end_dt = instrument.symbol, ctx.end_dt
    vendor = ctx.vendor
    empty = ctx.empty_ranges.get((vendor, symbol, timeframe))
    # The no-data evidence threshold is the item plan's (phase 190); the leaf module's own
    # constant is the fallback for a context built without one.
    min_confirmations = (
        ctx.plan.confirmation_chunks if ctx.plan is not None else ibkr._NO_DATA_CONFIRMATION_CHUNKS
    )

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
        min_confirmations=min_confirmations,
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
            vendor=vendor,
            **gate,
        )
        return [(midnight_utc(s), midnight_utc(e)) for s, e in gaps_d]
    if timeframe in _RECORD_PLAN_TFS:
        return detect_gaps_from_record(
            ctx.get_conn(),
            symbol,
            timeframe,
            start_dt,
            end_dt,
            expected_grid_slots(
                instrument.session_id, instrument.exchange, timeframe, start_dt, end_dt
            ),
            vendor=vendor,
            **gate,
        )
    conn = ctx.get_conn()
    gaps = detect_gaps(
        conn,
        symbol,
        timeframe,
        start_dt,
        end_dt,
        session_id=instrument.session_id,
        exchange=instrument.exchange,
        # Every timeframe stores real bars only (185-18, 185-32; migration 444 refuses a
        # synthetic_fill row), so the answered windows always load: they are all that keeps
        # a definitive no_data span from being re-asked forever (todo 462).
        answered=load_answered_windows(conn, symbol, timeframe, vendor),
        vendor=vendor,
    )
    kept = empty_history.apply_empty_range(
        gaps,
        empty,
        ctx.run_started_at,
        ctx.empty_reverify_days,
        timedelta(minutes=_TF_MINUTES[timeframe]),
        min_confirmations,
    )
    if kept != gaps and empty is not None:
        note_skip(empty)
    return kept


def _closed_sessions(first: date, now: datetime) -> list[date]:
    """NYSE session dates from `first` through now's date whose session has closed at `now`."""
    sessions = nyse_sessions(first, now.date())
    return [day for day in sessions if session_complete_at(day, now, sessions)]


def _with_verification_asks(
    ctx: FetchContext,
    timeframe: str,
    start_dt: datetime,
    gaps: list[tuple[datetime, datetime]],
    *,
    overlap: bool,
    refetch: bool,
) -> list[tuple[datetime, datetime]]:
    """The gap asks plus the re-asks that verify what the vendor already served.

    These are not gaps and the planner never produces them: a restated history (a split, a
    rescaled price level) shows only when stored slots are asked again and compared with
    the same source's own stored values, which is what the split detector and the update
    lane's overlap judgment read (plans 191-08 and 191-10). Without them no restatement is
    ever observed and the waiver that licenses a recorded split's refetch never fires. Kept
    on purpose, outside the gap question:

    - update lane (`overlap`, 5m): [start_dt, end) is re-asked behind the latest bar;
    - 1d (`ctx.overlap_sessions`): the last N sessions are re-asked so a split shows as a
      constant ratio (D-21);
    - escalation (`refetch`): the whole window, stored or not, after a restated overlap.
    """
    end_dt = ctx.end_dt
    if timeframe == "1d":
        gaps_d = [(a.date(), b.date()) for a, b in gaps]
        if refetch:
            window = _closed_sessions(start_dt.date(), end_dt)
            gaps_d = with_overlap_window(gaps_d, window, end_dt.date(), len(window))
        elif ctx.overlap_sessions > 0:
            # Sessions back from end, with calendar slack for weekends and holidays.
            overlap_days = int(ctx.overlap_sessions * 1.6) + 10
            gaps_d = with_overlap_window(
                gaps_d,
                _closed_sessions(end_dt.date() - timedelta(days=overlap_days), end_dt),
                end_dt.date(),
                ctx.overlap_sessions,
            )
        return [(midnight_utc(s), midnight_utc(e)) for s, e in gaps_d]
    if timeframe in _RECORD_PLAN_TFS and (refetch or overlap):
        return _merge_windows([*gaps, (start_dt, end_dt)])
    return gaps


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
    asks: Sequence[tuple[datetime, datetime]] | None = None,
) -> ItemOutcome:
    """Fetch one (symbol, timeframe) with the pipeline loop body's rules (CD-01/04/05).

    `asks` (the re-serve lane, 191-07 review finding 2): exactly these [start, end) windows are
    asked again, stored or not, instead of the planner's gaps; nothing is inferred about empty
    history from them. Every answer goes through the same persister and ingress contract.

    Plan 189-10's lanes (the fetcher decides them per item): the update lane asks a covered
    series from its latest bar, `overlap_days` earlier for a grid series, and reports the
    overlap's (stored, fresh) closes in overlap_pairs; full_scan plans the full depth (the
    gap-fill lane); refetch re-asks the whole depth including stored history (the
    escalation), through the waived grid writer when `waived` (a recorded corporate action).

    Ported from the historical pipeline script's main()._run_fetch_stage as it
    stands after plans 185-18 (shared gap planner, D1-only 1d), 185-19 (1d empty history
    reconciled from D1) and 185-22 (1d overlap). Changes versus the pipeline:
    - CD-04: every chunk persists atomically with its requests (and CoverageDelta, non-1d).
    - Todo 387: a fully covered series is planned from its latest bar, not 20 years back.
    - CD-05: the outcome is classified (ok / no_data / error) for the ledger.
    - CD-08: the clock is touched on every answered request and persisted chunk.
    - The head lookup, qualify and FX/crypto 1m deep fetch are cached per symbol per run.

    A 1d item stores its answers in ohlcv_raw only, one kind per route and what_to_show (D2 owns
    the canonical 1d grid). When it delivered bars it returns derive_1d_since; the caller runs
    the daily derivation stage for those symbols, as the pipeline did after its loop.

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
    head_floor: datetime | None = None
    if asks is not None:
        overlap = False
        gaps = _merge_windows(list(asks))
        if gaps:
            start_dt = gaps[0][0]
    else:
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

        gaps = _with_verification_asks(
            ctx,
            timeframe,
            start_dt,
            _plan_gaps(ctx, instrument, timeframe, start_dt),
            overlap=overlap,
            refetch=refetch,
        )
    clock.touch()
    if not gaps:
        return ItemOutcome(symbol, timeframe, "ok")

    windows = cluster_gap_ranges(gaps, max_gap_days=_history_fetch._GAP_CLUSTER_MAX_DAYS)
    d1_capture = timeframe == "1d"
    interval = timedelta(minutes=_TF_MINUTES[timeframe])
    use_cont = use_continuous and fetch_days > 14 and is_futures
    persister = _ChunkPersister(
        ctx, symbol, timeframe, clock, verify_overlap=overlap, waived=waived
    )
    capture = _capture_kwargs(ctx.sink, ctx.fetch_run_id)
    capture["on_request"] = persister.on_request
    # Every answer reaches the persister with its request record, intraday too, so each bar is
    # judged against the answer time and window end of the request that served it (finding 5).
    capture["on_observation"] = persister.on_observation

    n_returned = 0
    failed: list[str] = []
    reconcile_1d = False
    for gap_start, gap_end in windows:
        # Only the oldest window can be pre-history; its walk's definitive no-data answers
        # are what ohlcv_empty_history records.
        observed: list[EmptyHistory] = []
        is_oldest = asks is None and (gap_start, gap_end) == windows[0]
        # The record and D1 planners are end-exclusive (gap_end is the last missing slot's
        # end); the legacy planner's 1m range ends at the slot's start, so 1m asks through
        # the slot's end, capped at now so a bar still forming stays a gap.
        fetch_end = min(gap_end + interval, ctx.end_dt) if timeframe == "1m" else gap_end
        asked_at = datetime.now(UTC)
        try:
            bars = await ctx.provider.fetch_historical_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=gap_start,
                end=fetch_end,
                continuous=use_cont,
                on_chunk=None,
                on_empty_history=observed.append if is_oldest else None,
                **capture,
            )
            # A chunk that failed every retry does not raise; the window is incomplete.
            n_failed_chunks = getattr(ctx.provider, "last_fetch_failed_chunks", 0)
            if n_failed_chunks and _before_head(gap_end, head_floor):
                # The vendor holds nothing before its head: a failed ask for that span is not
                # a series failure and must not walk the series toward its exclusion.
                logger.info(
                    "ibkr_history_fetcher.failure_before_head_ignored",
                    symbol=symbol,
                    timeframe=timeframe,
                    window_end=str(gap_end.date()),
                )
            elif n_failed_chunks:
                failed.append(f"{gap_start.date()}-{gap_end.date()}: {n_failed_chunks} chunk(s)")
            n_returned += len(bars)
            if not d1_capture:
                # Defensive: the provider hands every answer to on_observation, but a returned
                # bar that missed it must still land with its coverage, never be dropped. With no
                # record, it is judged against the time the window was asked (a lower bound on
                # the answer) and the window's end.
                missed = [b for b in bars if b.timestamp not in persister.answered]
                if missed:
                    persister.persist(missed, answered_at=asked_at, request_end=fetch_end)
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
                        ctx.vendor,
                        (gap_start, gap_end),
                        observed[-1] if observed else None,
                        ctx.empty_ranges.get((ctx.vendor, symbol, timeframe)),
                        # chunk boundaries sit a day apart
                        timedelta(days=1) + interval,
                    )
        except Exception as error:
            if _before_head(gap_end, head_floor):
                logger.info(
                    "ibkr_history_fetcher.failure_before_head_ignored",
                    symbol=symbol,
                    timeframe=timeframe,
                    window_end=str(gap_end.date()),
                    error=str(error),
                )
                continue
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

    # Ledger flush once per item (phase 185 D-05): a failure raises, the item fails loudly.
    _flush_capture(ctx.sink, ctx.settings)
    if reconcile_1d:
        empty_history.reconcile_empty_history(ctx.get_conn(), "1d", ctx.vendor, symbols=[symbol])

    unmapped = tuple(persister.unmapped)
    if unmapped:
        failed.insert(0, "unmapped_kind: " + "; ".join(unmapped))
    failure = "; ".join(failed) if failed else None
    answered = n_bars > 0
    status = "error" if failed else ("ok" if answered else "no_data")
    return ItemOutcome(
        symbol,
        timeframe,
        status,
        n_bars=n_bars,
        n_grid_source_rows=n_bars if timeframe == _GRID_SOURCE_TF else 0,
        error=failure,
        derive_1d_since=start_dt if d1_capture and n_returned > 0 else None,
        overlap_pairs=tuple(persister.overlap_pairs),
        flags=tuple(persister.flags),
        n_basis_flagged=persister.n_basis_flagged,
        n_unselected=persister.n_unselected,
        unmapped=unmapped,
    )


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
    provider_plan: Any | None = None,
    asks: Sequence[tuple[datetime, datetime]] | None = None,
) -> ItemOutcome:
    """fetch_item under the stall bound, retried after a stall at most request_retries
    times (CD-08).

    The request budget comes from `provider_plan` (the item's ProviderPlan, phase 190
    plan 04) when given, falling back to the QueueConfig mirrors for callers that pass
    no plan (config.history_request_timeout_s / history_request_retries).

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
    if provider_plan is not None:
        stall_timeout_s = provider_plan.request_timeout_s
        retries = provider_plan.request_retries
    else:
        stall_timeout_s = config.history_request_timeout_s
        retries = config.history_request_retries
    max_attempts = 1 + retries

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
                asks=asks,
            )

        try:
            outcome: ItemOutcome = await run_with_stall_bound(
                attempt_coro,
                stall_timeout_s=stall_timeout_s,
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
