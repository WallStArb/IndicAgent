"""Deterministic priority queue for the IBKR history fetcher (phase 189 plan 02, CD-06).

The fetcher works one (symbol, timeframe) series at a time, in the order this module gives.
Ranking is a pure function of a coverage row (ohlcv_coverage, migration 432), the symbol's
proven depth, APR config and today's date, so the dry run and the real run produce the same
order. The design tuple, verbatim:

    rank(symbol, timeframe) = (
        consecutive_failures > infra.backfill.max_consecutive_failures,  -- excluded, lowest
        timeframe != '1d',                              -- due 1d first (189-10, 185-46 B)
        staleness_days <= infra.backfill.max_staleness_days_before_preempt,  -- SLA band first
        -1 if timeframe in priority_tf_order else 0,   -- 15m/1h before 5m (todo 449)
        -coverage_gap_days,                             -- zero/largest gap first
        -staleness_days,                                -- nightly freshness falls out of this
        symbol                                          -- deterministic tie-break
    )

Why each element exists:

- Excluded: a series that keeps erroring (CD-08) must not hold the head of the queue every
  run. 'no_data' is a correct empty answer, never a failure (CD-05): only 'error' outcomes
  increment consecutive_failures, so a no_data series is never excluded.
- Due 1d first: IBKR is the 1d primary (owner decision 2026-10-07), so one short 1d ask per
  name after each close must never wait behind the 5m drain. Every queued 1d item is due (the
  1d due rule holds the rest), and it ranks ahead of every other item. It sits before the SLA
  band rather than in the timeframe class because an SLA-breached 5m series would otherwise
  still rank first.
- SLA band: without it a permanent bulk backlog (one newly onboarded zero-coverage symbol)
  could block freshness updates for 900+ covered names for hours with nothing surfacing it.
- Timeframe class: the owner's todo 449 decision, 15m/1h ahead of 5m/1d.
- Coverage gap: the ceiling insight carried over from the pipeline's
  _reorder_contracts_by_gap. A symbol's own proven depth (its deepest stored series, any
  timeframe, 1d included) caps the fetchable gap, so a young ETF's inception wall never
  looks like missing data. The provider's verified floor caps it too (below).
- Staleness: nightly freshness needs no separate code path; yesterday's series ranks by it.
- symbol, then timeframe: total order, so two series never tie and output is stable under
  any input order.

Interpretation choices (documented because the design tuple leaves them open):

1. The SLA element is ``not sla_breach`` with ``sla_breach = latest_timestamp is not None
   and staleness_days > max_staleness_days_before_preempt``. Only covered series that fell
   behind enter the preempt band; a never-fetched series has no staleness and is not in it,
   or it would preempt every covered series and recreate the starvation the band prevents.
2. A never-fetched series sorts as maximally stale in the staleness element: its timeframe's
   target depth (``depth_days``) stands in for the missing staleness.
3. Proven depth is unknown (None) for a symbol with no stored bars in any timeframe. The
   target depth then stands in for the ceiling, so a newly onboarded name is fetched once
   instead of scoring a permanent zero gap; the first answer proves its depth (or records
   its provider floor) and the ceiling applies from then on.
4. Provider floor: the later of a fresh ohlcv_provider_head.head_ts for the symbol and the
   empty_through of a fresh, sufficiently confirmed ohlcv_empty_history range for the series.
   Venue-boundary names (TLT/AMD/PEP, todo 433) then do not show a permanent fetchable gap
   for verified-empty history. A range confirmed by fewer than
   infra.ibkr.no_data_confirmation_chunks answers is not trusted (todo 049), as in
   _empty_history.apply_empty_range.

Thresholds come from QueueConfig (APR); the only literals are schema identifiers and the
provider name. No IBKR access and no writes.

Two lanes, one queue (plan 189-10 Task 1, as amended by 185-46): every item is one of
- the update lane: the series is asked since its latest stored bar, widened to overlap the
  stored tail (1d: infra.backfill.update_overlap_sessions_1d sessions; 5m:
  infra.backfill.update_overlap_days_5m days); judge_overlap compares the overlap to the stored
  bars and the fetcher escalates a breach to a full-depth re-fetch in the same run;
- the gap-fill lane: on one session in every infra.backfill.gap_fill_interval_days
  (gap_fill_due) the series plans its full depth instead (interior holes, short starts).
A 1d series is due by the session calendar and the request ledger (daily_due_reason), the
other timeframes by is_current. The weekly parity sample (parity_sample) adds vendor 15m and 1h
items for a few names a week. The keys live in LaneConfig (load_lane_config, no fallbacks:
migration 451 seeds them).
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog

from scripts.infrastructure.backfill._empty_history import _REVERIFY_DAYS_KEY

logger = structlog.get_logger(__name__)

PROVIDER = "ibkr"
# The timeframe the 1d due rule and the due-1d-first rank element apply to (a DAG fact: 1d is
# the one timeframe with a session-calendar currency rule and a nightly reconcile).
DAILY_TF = "1d"

_KEY_MAX_FAILURES = "infra.backfill.max_consecutive_failures"
_KEY_SLA_DAYS = "infra.backfill.max_staleness_days_before_preempt"
_KEY_PRIORITY_TFS = "infra.backfill.priority_tf_order"
_KEY_DEFAULT_SCOPES = "infra.backfill.default_scopes"
_KEY_RUN_BUDGET = "infra.backfill.run_budget_minutes"
_KEY_REQUEST_TIMEOUT = "infra.ibkr.history_request_timeout"
_KEY_REQUEST_RETRIES = "infra.ibkr.history_request_retries"
_KEY_RATE_LIMIT_WINDOW = "infra.ibkr.rate_limit_window_sec"
_KEY_CONFIRMATION_CHUNKS = "infra.ibkr.no_data_confirmation_chunks"
_DEPTH_PREFIX = "infra.backfill.depth_days."

# Fallbacks: the migration 432 seeds, the pipeline's _TF_FETCH_CONFIG depths and ibkr.py's
# rate-limit window. Used only when a key is missing, and logged when used.
_FALLBACKS: dict[str, str] = {
    _KEY_MAX_FAILURES: "5",
    _KEY_SLA_DAYS: "3",
    _KEY_PRIORITY_TFS: '["15m", "1h"]',
    _KEY_DEFAULT_SCOPES: (
        '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}'
    ),
    _KEY_RUN_BUDGET: "240",
    _KEY_REQUEST_TIMEOUT: "900",
    _KEY_REQUEST_RETRIES: "2",
    _KEY_RATE_LIMIT_WINDOW: "600.0",
}
_DEPTH_FALLBACKS: dict[str, int] = {"1d": 7300, "1h": 7300, "15m": 7300, "5m": 7300, "1m": 90}


@dataclass(frozen=True)
class QueueConfig:
    max_consecutive_failures: int
    max_staleness_days_before_preempt: int
    priority_tf_order: tuple[str, ...]
    depth_days: Mapping[str, int]
    history_request_timeout_s: float
    history_request_retries: int
    run_budget_minutes: int
    default_scopes: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class CoverageRow:
    symbol: str
    timeframe: str
    earliest_timestamp: datetime | None
    latest_timestamp: datetime | None
    last_fetch_status: str | None
    consecutive_failures: int
    floor_timestamp: datetime | None
    last_fetched_at: datetime | None = None


# Outcomes after which a series has nothing new to ask until the next session closes.
_SETTLED_STATUSES = frozenset({"ok", "no_data"})


def is_current(row: CoverageRow, current_after: datetime | None) -> bool:
    """True when the series' last fetch settled (ok or no_data) at or after `current_after`,
    the latest completed session close (phase 189 plan 04).

    Such a series has nothing new to ask: its last item planned every fetchable window and
    no session has closed since. Without this hold, a recurring fetcher re-asks every
    gap-free series on every fire (every intraday series' newest slots during market hours,
    every 1d series' overlap window), spending the one IBKR stream on answers it already
    has. An 'error' series is never current, so it is retried until excluded. Parameter-
    free: the session calendar, not a tunable interval, decides when new data can exist.
    """
    return (
        current_after is not None
        and row.last_fetched_at is not None
        and row.last_fetch_status in _SETTLED_STATUSES
        and row.last_fetched_at >= current_after
    )


@dataclass(frozen=True)
class RankedItem:
    """A row with its rank tuple and the components the dry run reports."""

    row: CoverageRow
    rank: tuple[Any, ...]
    sla_breach: bool
    tf_class: int
    gap_days: int
    staleness_days: int | None


def load_queue_config(conn: Any) -> QueueConfig:
    """Read the fetcher's APR keys in one query (psycopg connection).

    Malformed JSON raises (json.JSONDecodeError is a ValueError). Raises ValueError when the
    per-item stall bound does not exceed the rate limiter's window: the limiter sleeps
    silently up to that long, so a smaller bound would cancel healthy items.
    """
    keys = list(_FALLBACKS)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key = ANY(%s) OR config_key LIKE %s",
            (keys, _DEPTH_PREFIX + "%"),
        )
        rows = cur.fetchall()
    values = {str(k): str(v) for k, v in rows}
    missing = sorted(k for k in keys if k not in values)
    depth_days = dict(_DEPTH_FALLBACKS)
    for key, value in values.items():
        if key.startswith(_DEPTH_PREFIX):
            depth_days[key[len(_DEPTH_PREFIX) :]] = int(value)
    missing_depths = sorted(
        _DEPTH_PREFIX + tf for tf in _DEPTH_FALLBACKS if _DEPTH_PREFIX + tf not in values
    )
    if missing or missing_depths:
        logger.warning("fetch_queue.apr_fallback_used", keys=missing + missing_depths)

    def get(key: str) -> str:
        return values.get(key, _FALLBACKS[key])

    timeout_s = float(get(_KEY_REQUEST_TIMEOUT))
    window_s = float(get(_KEY_RATE_LIMIT_WINDOW))
    if timeout_s <= window_s:
        raise ValueError(
            f"{_KEY_REQUEST_TIMEOUT}={timeout_s} must exceed "
            f"{_KEY_RATE_LIMIT_WINDOW}={window_s}: the stall bound would cancel healthy "
            "items during a rate-limit sleep"
        )
    scopes = json.loads(get(_KEY_DEFAULT_SCOPES))
    return QueueConfig(
        max_consecutive_failures=int(get(_KEY_MAX_FAILURES)),
        max_staleness_days_before_preempt=int(get(_KEY_SLA_DAYS)),
        priority_tf_order=tuple(json.loads(get(_KEY_PRIORITY_TFS))),
        depth_days=depth_days,
        history_request_timeout_s=timeout_s,
        history_request_retries=int(get(_KEY_REQUEST_RETRIES)),
        run_budget_minutes=int(get(_KEY_RUN_BUDGET)),
        default_scopes={str(k): tuple(v) for k, v in scopes.items()},
    )


# ---------------------------------------------------------------------------
# Lanes (plan 189-10 Task 1, as amended by 185-46)
# ---------------------------------------------------------------------------

_KEY_RECONCILE_INTERVAL = "infra.backfill.ibkr_1d_reconcile_interval_days"
_KEY_OVERLAP_1D = "infra.backfill.update_overlap_sessions_1d"
_KEY_OVERLAP_5M = "infra.backfill.update_overlap_days_5m"
_KEY_GAP_FILL_INTERVAL = "infra.backfill.gap_fill_interval_days"
_KEY_PARITY_NAMES = "infra.backfill.grid_parity_sample_names_per_week"
BASIS_TOLERANCE_KEY = "threshold.bar_integrity.fallback_basis_tolerance_bp"
LANE_KEYS = (
    _KEY_RECONCILE_INTERVAL,
    _KEY_OVERLAP_1D,
    _KEY_OVERLAP_5M,
    _KEY_GAP_FILL_INTERVAL,
    _KEY_PARITY_NAMES,
    BASIS_TOLERANCE_KEY,
)
# Basis points per unit ratio (a unit conversion).
_BP = 10_000.0
# Monday 2000-01-03: the origin of the weekday index gap_fill_due counts from (any Monday works;
# fixed so a series keeps its slot across runs).
_WEEKDAY_ORIGIN = date(2000, 1, 3)
_WEEKDAYS = 5


@dataclass(frozen=True)
class LaneConfig:
    """The two lanes' and the parity sample's APR keys (migration 451) plus the overlap
    tolerance (threshold.bar_integrity.fallback_basis_tolerance_bp, migration 446's)."""

    reconcile_interval_sessions: int
    update_overlap_sessions_1d: int
    update_overlap_days_5m: int
    gap_fill_interval_days: int
    parity_names_per_week: int
    basis_tolerance_bp: float


def load_lane_config(conn: Any) -> LaneConfig:
    """Read LANE_KEYS in one query (psycopg). No fallbacks: a missing key raises, because a
    silent default would change what the fetcher asks the provider."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            (list(LANE_KEYS),),
        )
        values = {str(k): str(v) for k, v in cur.fetchall()}
    missing = sorted(set(LANE_KEYS) - set(values))
    if missing:
        raise RuntimeError(f"APR keys not set (migration 451): {missing}")
    return LaneConfig(
        reconcile_interval_sessions=int(values[_KEY_RECONCILE_INTERVAL]),
        update_overlap_sessions_1d=int(values[_KEY_OVERLAP_1D]),
        update_overlap_days_5m=int(values[_KEY_OVERLAP_5M]),
        gap_fill_interval_days=int(values[_KEY_GAP_FILL_INTERVAL]),
        parity_names_per_week=int(values[_KEY_PARITY_NAMES]),
        basis_tolerance_bp=float(values[BASIS_TOLERANCE_KEY]),
    )


@dataclass(frozen=True)
class DailyRule:
    """The session calendar's inputs to the 1d due rule: the latest completed session's close
    and the close a name's latest answered request must postdate (reconcile_after)."""

    last_close: datetime
    reconcile_after: datetime


def reconcile_after(closes: Sequence[datetime], interval_sessions: int) -> datetime:
    """The close of the Nth latest completed session (closes ascending, N >= 1). N = 1 is the
    latest close: every name is asked once after every session."""
    if interval_sessions < 1 or interval_sessions > len(closes):
        raise ValueError(
            f"reconcile interval {interval_sessions} outside 1..{len(closes)} known closes"
        )
    return sorted(closes)[-interval_sessions]


def daily_due_reason(
    latest_answered: datetime | None, latest_canonical: date | None, rule: DailyRule
) -> str | None:
    """Why a name's 1d item is due, or None when it is held as current.

    - never_asked: no answered SMART TRADES 1d request exists.
    - reconcile_due: the latest answer predates rule.reconcile_after (owner rule, 185-46
      amendment B: with the interval at 1, answered before the latest completed close).
    - not_current: the latest canonical bar is not the last completed session and the name
      was not asked since that close. A name asked since the close stays held even when its
      canonical bar is stale (the freshness_1d verdict names it); re-asking it every run would
      spend the stream on an answer that already came back.
    """
    if latest_answered is None:
        return "never_asked"
    if latest_answered < rule.reconcile_after:
        return "reconcile_due"
    stale = latest_canonical is None or latest_canonical < rule.last_close.date()
    if stale and latest_answered < rule.last_close:
        return "not_current"
    return None


def _stable_int(*parts: str) -> int:
    digest = hashlib.sha256("\x1f".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def gap_fill_due(symbol: str, timeframe: str, session_day: date, interval_sessions: int) -> bool:
    """True on one weekday session in every `interval_sessions` for this series.

    The slot is the series' stable hash modulo the interval, matched against the weekday
    index of `session_day` (the last completed session), so the gap-fill work spreads evenly
    over the cycle and needs no stored state. A slot that falls on a market holiday skips that
    cycle; the update lane's overlap still verifies the tail meanwhile.
    """
    if interval_sessions <= 1:
        return True
    days = (session_day - _WEEKDAY_ORIGIN).days
    weekday_index = (days // 7) * _WEEKDAYS + min(days % 7, _WEEKDAYS)
    return (weekday_index + _stable_int(symbol, timeframe)) % interval_sessions == 0


def parity_week_start(day: date) -> datetime:
    """00:00 UTC on the Monday of `day`'s ISO week: a parity series asked since then is held."""
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


def parity_sample(eligible: Iterable[str], day: date, n: int) -> list[str]:
    """The `n` names of `day`'s ISO week: the same on every run that week, a new draw the next.

    Ordered by a hash of (ISO year, ISO week, symbol), so the draw needs no state and does not
    depend on the input order. Eligibility (5m rows and archive rows) is the caller's read.
    """
    if n <= 0:
        return []
    year, week, _ = day.isocalendar()
    names = sorted(set(eligible))
    return sorted(names, key=lambda s: (_stable_int(str(year), str(week), s), s))[:n]


@dataclass(frozen=True)
class OverlapVerdict:
    """The update lane's comparison of an overlap with the stored bars."""

    n_pairs: int
    median_ratio: float | None
    n_restated: int
    escalate: bool
    reason: str | None


def judge_overlap(
    pairs: Sequence[tuple[float, float]], tolerance_bp: float, *, escalate_on_restated: bool
) -> OverlapVerdict:
    """Judge (stored close, fresh close) pairs of one series' overlap.

    Escalates when the median stored/fresh close ratio is outside `tolerance_bp` (a rescale:
    a split, or a vendor basis change), or, with `escalate_on_restated`, when any close was
    restated. 1d escalates on any restated close (1 in 5,558 repeated SMART TRADES
    observations of completed sessions moved, 2026-10-07; volume never enters). 5m does not:
    IBKR restates 15 to 40 recent intraday rows a name routinely (185-31), which the ingress
    contract writes and records in ohlcv_revision.
    """
    usable = [(s, f) for s, f in pairs if f]
    if not usable:
        return OverlapVerdict(0, None, 0, False, None)
    ratio = statistics.median(s / f for s, f in usable)
    n_restated = sum(1 for s, f in usable if s != f)
    if abs(ratio - 1.0) * _BP > tolerance_bp:
        reason: str | None = "ratio_outside_tolerance"
    elif escalate_on_restated and n_restated:
        reason = "restated_row"
    else:
        reason = None
    return OverlapVerdict(len(usable), ratio, n_restated, reason is not None, reason)


def _days_since(ts: datetime, today: date) -> int:
    return (today - ts.astimezone(UTC).date()).days


def staleness_days(row: CoverageRow, today: date) -> int | None:
    """Days since the latest stored bar (UTC dates); None when never fetched."""
    if row.latest_timestamp is None:
        return None
    return _days_since(row.latest_timestamp, today)


def coverage_gap_days(
    row: CoverageRow, proven_days: int | None, target_days: int, today: date
) -> int:
    """Fetchable history missing from the series, in days.

    ceiling = min(proven depth, target depth, provider floor depth); gap = ceiling minus the
    series' actual depth, never negative. Unknown proven depth leaves the ceiling at the
    target (and floor).
    """
    actual = 0 if row.earliest_timestamp is None else _days_since(row.earliest_timestamp, today)
    ceiling = target_days
    if proven_days is not None:
        ceiling = min(ceiling, proven_days)
    if row.floor_timestamp is not None:
        ceiling = min(ceiling, _days_since(row.floor_timestamp, today))
    return max(0, ceiling - actual)


def proven_days_by_symbol(rows: Iterable[CoverageRow], today: date) -> dict[str, int]:
    """Per symbol, the deepest stored series in days over every timeframe it has.
    Symbols with no stored bars at all are absent (proven depth unknown)."""
    proven: dict[str, int] = {}
    for row in rows:
        if row.earliest_timestamp is None:
            continue
        depth = _days_since(row.earliest_timestamp, today)
        if depth > proven.get(row.symbol, -1):
            proven[row.symbol] = depth
    return proven


def _components(
    row: CoverageRow, proven_days: int | None, config: QueueConfig, today: date
) -> RankedItem:
    stale = staleness_days(row, today)
    sla_breach = stale is not None and stale > config.max_staleness_days_before_preempt
    tf_class = -1 if row.timeframe in config.priority_tf_order else 0
    target = config.depth_days.get(row.timeframe, 0)
    gap = coverage_gap_days(row, proven_days, target, today)
    effective_stale = target if stale is None else stale
    key = (
        row.consecutive_failures > config.max_consecutive_failures,
        row.timeframe != DAILY_TF,
        not sla_breach,
        tf_class,
        -gap,
        -effective_stale,
        row.symbol,
        row.timeframe,
    )
    return RankedItem(row, key, sla_breach, tf_class, gap, stale)


def rank(
    row: CoverageRow, proven_days: int | None, config: QueueConfig, today: date
) -> tuple[Any, ...]:
    """The design tuple plus timeframe as a final element. Pure: no I/O."""
    return _components(row, proven_days, config, today).rank


def queue_items(
    rows: Iterable[CoverageRow],
    config: QueueConfig,
    today: date,
    proven: Mapping[str, int] | None = None,
) -> list[RankedItem]:
    """Non-excluded rows in rank order, with components. `proven` defaults to the depth the
    rows themselves prove; pass a mapping computed over a wider row set to rank a subset."""
    rows = list(rows)
    if proven is None:
        proven = proven_days_by_symbol(rows, today)
    items = [_components(r, proven.get(r.symbol), config, today) for r in rows]
    return sorted((i for i in items if not i.rank[0]), key=lambda i: i.rank)


def order_queue(
    rows: Iterable[CoverageRow],
    config: QueueConfig,
    today: date,
    proven: Mapping[str, int] | None = None,
) -> list[CoverageRow]:
    """Excluded rows dropped, the rest ascending by rank. Pure."""
    return [i.row for i in queue_items(rows, config, today, proven)]


_COVERAGE_SQL = (
    "SELECT symbol, timeframe, earliest_timestamp, latest_timestamp, last_fetch_status, "
    "consecutive_failures, last_fetched_at FROM ohlcv_coverage WHERE symbol = ANY($1::text[])"
)
_CONFIG_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])"
_HEADS_SQL = (
    "SELECT symbol, head_ts FROM ohlcv_provider_head WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3)"
)
_EMPTY_SQL = (
    "SELECT symbol, timeframe, empty_through FROM ohlcv_empty_history WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3) "
    "AND n_confirming_chunks >= $4"
)
# The 1d due rule's two reads: each name's latest answered SMART TRADES 1d request (test callers
# never count, as in services/split_detection.py) and its latest canonical 1d bar inside a
# lookback (absent there reads as stale).
_LATEST_DAILY_ANSWER_SQL = (
    "SELECT symbol, max(answered_at) AS answered_at FROM ohlcv_request "
    "WHERE source = $1 AND timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES' "
    "AND outcome IN ('bars', 'no_data') AND caller NOT LIKE 'test-%' "
    "AND symbol = ANY($2::text[]) GROUP BY symbol"
)
_LATEST_CANONICAL_1D_SQL = (
    'SELECT symbol, max("timestamp") AS latest FROM market_data_ohlcv_tradeable '
    "WHERE timeframe = '1d' AND symbol = ANY($1::text[]) AND \"timestamp\" >= $2 "
    "GROUP BY symbol"
)
# Calendar slack for the canonical lookback: longer than any market closure, so a current name
# always has its latest bar inside it. A calendar fact, not a tunable.
_CANONICAL_LOOKBACK_DAYS = 14


@dataclass
class PriorityQueue:
    """The fetcher's queue over candidate (symbol, timeframe) pairs.

    load() reads every ledger row of the candidate symbols (all timeframes, so proven depth
    sees 1d even when 1d is out of scope) plus fresh provider floors; next() reloads and
    returns the first unvisited item. Reloading per item is cheap (a few thousand rows) and
    keeps the order in step with what the previous fetch just wrote.

    `current_after` (the latest completed session close) holds back series that are current
    (is_current); held_snapshot() reports them and the excluded series for the dry run.
    """

    config: QueueConfig
    candidates: Sequence[tuple[str, str]]
    today: date
    current_after: datetime | None = None
    # The 1d due rule (None: 1d series follow is_current like the rest, e.g. named symbols).
    daily: DailyRule | None = None
    # Per-series hold point replacing current_after (the parity sample: its ISO week start).
    current_after_by_series: Mapping[tuple[str, str], datetime] = field(default_factory=dict)
    _items: list[RankedItem] = field(default_factory=list, init=False, repr=False)
    _held: list[tuple[RankedItem, str]] = field(default_factory=list, init=False, repr=False)
    _daily_inputs: tuple[dict[str, datetime], dict[str, date]] | None = field(
        default=None, init=False, repr=False
    )
    _due_reasons: dict[tuple[str, str], str] = field(default_factory=dict, init=False, repr=False)

    async def load(self, pool: Any) -> None:
        symbols = sorted({s for s, _ in self.candidates})
        async with pool.acquire() as conn:
            cfg_rows = await conn.fetch(_CONFIG_SQL, [_REVERIFY_DAYS_KEY, _KEY_CONFIRMATION_CHUNKS])
            cfg = {r["config_key"]: r["config_value"] for r in cfg_rows}
            for key in (_REVERIFY_DAYS_KEY, _KEY_CONFIRMATION_CHUNKS):
                if key not in cfg:
                    raise RuntimeError(f"APR key {key!r} is not set")
            reverify_days = int(cfg[_REVERIFY_DAYS_KEY])
            min_confirmations = int(cfg[_KEY_CONFIRMATION_CHUNKS])
            coverage = await conn.fetch(_COVERAGE_SQL, symbols)
            heads = await conn.fetch(_HEADS_SQL, PROVIDER, symbols, reverify_days)
            empties = await conn.fetch(
                _EMPTY_SQL, PROVIDER, symbols, reverify_days, min_confirmations
            )
        head_by_symbol = {r["symbol"]: r["head_ts"] for r in heads}
        empty_by_series = {(r["symbol"], r["timeframe"]): r["empty_through"] for r in empties}

        def floor(symbol: str, timeframe: str) -> datetime | None:
            found = [
                ts
                for ts in (head_by_symbol.get(symbol), empty_by_series.get((symbol, timeframe)))
                if ts is not None
            ]
            return max(found) if found else None

        all_rows = {
            (r["symbol"], r["timeframe"]): CoverageRow(
                symbol=r["symbol"],
                timeframe=r["timeframe"],
                earliest_timestamp=r["earliest_timestamp"],
                latest_timestamp=r["latest_timestamp"],
                last_fetch_status=r["last_fetch_status"],
                consecutive_failures=int(r["consecutive_failures"]),
                floor_timestamp=floor(r["symbol"], r["timeframe"]),
                last_fetched_at=r["last_fetched_at"],
            )
            for r in coverage
        }
        proven = proven_days_by_symbol(all_rows.values(), self.today)
        candidate_rows = [
            all_rows.get((s, tf)) or CoverageRow(s, tf, None, None, None, 0, floor(s, tf))
            for s, tf in dict.fromkeys(self.candidates)
        ]
        if self.daily is not None and self._daily_inputs is None:
            daily_symbols = sorted({s for s, tf in self.candidates if tf == DAILY_TF})
            self._daily_inputs = await self._load_daily_inputs(pool, daily_symbols)
        self._due_reasons = {}
        due = [r for r in candidate_rows if self._is_due(r)]
        self._items = queue_items(due, self.config, self.today, proven)
        queued = {(i.row.symbol, i.row.timeframe) for i in self._items}
        held = [
            _components(r, proven.get(r.symbol), self.config, self.today)
            for r in candidate_rows
            if (r.symbol, r.timeframe) not in queued
        ]
        self._held = sorted(
            ((i, "excluded" if i.rank[0] else "current") for i in held),
            key=lambda pair: pair[0].rank,
        )

    async def _load_daily_inputs(
        self, pool: Any, symbols: list[str]
    ) -> tuple[dict[str, datetime], dict[str, date]]:
        """The 1d due rule's reads, once per queue (a run): an item fetched later in the run is
        kept out by the run's visited set, so a fresher read would change nothing."""
        if not symbols or self.daily is None:
            return {}, {}
        since = self.daily.last_close - timedelta(days=_CANONICAL_LOOKBACK_DAYS)
        async with pool.acquire() as conn:
            answers = await conn.fetch(_LATEST_DAILY_ANSWER_SQL, PROVIDER, symbols)
            canonical = await conn.fetch(_LATEST_CANONICAL_1D_SQL, symbols, since)
        return (
            {r["symbol"]: r["answered_at"] for r in answers},
            {r["symbol"]: r["latest"].astimezone(UTC).date() for r in canonical},
        )

    def _is_due(self, row: CoverageRow) -> bool:
        key = (row.symbol, row.timeframe)
        if row.timeframe == DAILY_TF and self.daily is not None and self._daily_inputs:
            if row.last_fetch_status == "error":  # never held, as is_current
                self._due_reasons[key] = "error"
                return True
            answered, canonical = self._daily_inputs
            reason = daily_due_reason(
                answered.get(row.symbol), canonical.get(row.symbol), self.daily
            )
            if reason is not None:
                self._due_reasons[key] = reason
            return reason is not None
        return not is_current(row, self.current_after_by_series.get(key, self.current_after))

    def due_reason(self, symbol: str, timeframe: str) -> str:
        """Why the last load() queued a 1d series under the daily rule ('' otherwise)."""
        return self._due_reasons.get((symbol, timeframe), "")

    async def next(self, pool: Any, visited: set[tuple[str, str]]) -> CoverageRow | None:
        """The highest-ranked item not yet visited this run; None when exhausted."""
        await self.load(pool)
        for item in self._items:
            if (item.row.symbol, item.row.timeframe) not in visited:
                return item.row
        return None

    def ranked_snapshot(self) -> list[RankedItem]:
        """The order from the last load(), with rank tuples and components (dry run)."""
        return list(self._items)

    def held_snapshot(self) -> list[tuple[RankedItem, str]]:
        """Candidates the last load() kept out of the order, each with its reason:
        'excluded' (past the failure threshold) or 'current' (is_current)."""
        return list(self._held)
