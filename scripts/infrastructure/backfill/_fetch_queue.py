"""Deterministic priority queue for the IBKR history fetcher (phase 189 plan 02, CD-06).

The fetcher works one (symbol, timeframe) series at a time, in the order this module gives.
Ranking is a pure function of a coverage row (ohlcv_coverage, migration 432), the symbol's
proven depth, APR config and today's date, so the dry run and the real run produce the same
order. The design tuple, verbatim:

    rank(provider, symbol, timeframe) = (
        consecutive_failures > infra.backfill.max_consecutive_failures,  -- excluded, lowest
        timeframe != '1d',                              -- due 1d first (189-10, 185-46 B)
        staleness_days <= infra.backfill.max_staleness_days_before_preempt,  -- SLA band first
        -1 if timeframe in priority_tf_order else 0,   -- 15m/1h before 5m (todo 449)
        -coverage_gap_days,                             -- zero/largest gap first
        -staleness_days,                                -- nightly freshness falls out of this
        symbol,                                         -- deterministic tie-break
        provider                                        -- phase 190: planes never tie
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

Provider dimension (phase 190 plan 03): every ledger read, floor and failure count is
per-provider (the two-tier ledger: one vendor's outage or head never ranks or excludes
another vendor's items), per-provider planner inputs live in ProviderPlan
(load_provider_plan, infra.<provider>.* APR keys), and item creation is gated by the
bar_source_policy tier (policy_authorizes, read-only). Candidates, items, due reasons and
visited keys are (provider, symbol, timeframe) triples internally; the legacy (symbol,
timeframe) pair call shapes are accepted everywhere and default to the ibkr plane, because
the unmodified fetcher calls this module until 190-04 (the compatibility contract).

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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog

from scripts.infrastructure.backfill._empty_history import _REVERIFY_DAYS_KEY

logger = structlog.get_logger(__name__)

# The timeframe the 1d due rule and the due-1d-first rank element apply to (a DAG fact: 1d is
# the one timeframe with a session-calendar currency rule and a nightly reconcile).
DAILY_TF = "1d"

# The IBKR 1d answer shape (a provider-native request shape, like the coverage writer's
# per-provider rebuild filters): the daily due rule's request-ledger filter. A vendor whose
# plan has answers_1d=False never issues this query and never gets 1d items (pitfall 4).
_IBKR_DAILY_ANSWER_FILTER = "route = 'SMART' AND what_to_show = 'TRADES'"

_KEY_MAX_FAILURES = "infra.backfill.max_consecutive_failures"
_KEY_SLA_DAYS = "infra.backfill.max_staleness_days_before_preempt"
_KEY_PRIORITY_TFS = "infra.backfill.priority_tf_order"
_KEY_DEFAULT_SCOPES = "infra.backfill.default_scopes"
_KEY_RUN_BUDGET = "infra.backfill.run_budget_minutes"
_DEPTH_PREFIX = "infra.backfill.depth_days."

# Per-provider APR key suffixes under infra.<provider>.* (phase 190 plan 03 Task 1).
_PROVIDER_TIMEOUT_KEY = "history_request_timeout"
_PROVIDER_RETRIES_KEY = "history_request_retries"
_PROVIDER_WINDOW_KEY = "rate_limit_window_sec"
_PROVIDER_CONFIRMATION_KEY = "no_data_confirmation_chunks"
_PROVIDER_PAUSE_KEY = "inter_item_pause_s"
_PROVIDER_DEPTH_PREFIX = "depth_days."
# The ibkr planner keys, listed for the one batched config_state query. The provider name is
# a literal here and in every fetcher-compatible default below: until 190-04 passes plans,
# the unmodified fetcher's calls all default to the ibkr plane.
_PROVIDER_PLAN_KEYS = (
    f"infra.ibkr.{_PROVIDER_TIMEOUT_KEY}",
    f"infra.ibkr.{_PROVIDER_RETRIES_KEY}",
    f"infra.ibkr.{_PROVIDER_WINDOW_KEY}",
    f"infra.ibkr.{_PROVIDER_CONFIRMATION_KEY}",
    f"infra.ibkr.{_PROVIDER_PAUSE_KEY}",
)
_KEY_CONFIRMATION_CHUNKS = f"infra.ibkr.{_PROVIDER_CONFIRMATION_KEY}"

# Fallbacks: the migration 432 seeds and the pipeline's _TF_FETCH_CONFIG depths, for the
# provider-neutral keys only. Used only when a key is missing, and logged when used. The
# per-provider planner inputs have no fallback (they raise); the one leaf-native fallback is
# the provider rate-limit window, inside load_provider_plan.
_FALLBACKS: dict[str, str] = {
    _KEY_MAX_FAILURES: "5",
    _KEY_SLA_DAYS: "3",
    _KEY_PRIORITY_TFS: '["15m", "1h"]',
    _KEY_DEFAULT_SCOPES: (
        '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}'
    ),
    _KEY_RUN_BUDGET: "240",
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
class ProviderPlan:
    """One provider's planner inputs (phase 190 design's budget interface): its request
    budget and native semantics as data, never module constants or branches on vendor.

    Numerics come from infra.<provider>.* APR keys through load_provider_plan. answers_1d
    and daily_answer_filter are provider-native request data (IBKR answers 1d via SMART
    TRADES; a REST vendor with no 1d sets answers_1d=False and gets no 1d items, pitfall 4).
    depth_overrides optionally cap the neutral depth map per timeframe for this provider
    (infra.<provider>.depth_days.<tf>); no seeds are required to stay on the neutral map.
    """

    name: str
    request_timeout_s: float
    request_retries: int
    rate_limit_window_s: float
    confirmation_chunks: int
    inter_item_pause_s: float
    answers_1d: bool = True
    daily_answer_filter: str | None = _IBKR_DAILY_ANSWER_FILTER
    depth_overrides: Mapping[str, int] = field(default_factory=dict)


def default_provider() -> str:
    """The fetcher-compatible default planning plane: every entry point the unmodified
    fetcher calls (plan 190-03's compatibility contract) defaults to the ibkr plane until
    190-04 passes providers and plans explicitly."""
    return "ibkr"


def _series_key(key: Sequence[str]) -> tuple[str, str, str]:
    """Normalize a series key to the canonical (provider, symbol, timeframe) triple: the
    legacy (symbol, timeframe) pair shape is accepted and defaults to the ibkr plane."""
    if len(key) == 2:
        return (default_provider(), key[0], key[1])
    if len(key) == 3:
        return (key[0], key[1], key[2])
    raise ValueError(
        f"series key must be (provider, symbol, timeframe) or (symbol, timeframe): {key}"
    )


def load_provider_plan(
    provider: str,
    get: Callable[[str], str | None],
    *,
    answers_1d: bool = True,
    daily_answer_filter: str | None = _IBKR_DAILY_ANSWER_FILTER,
    depth_tfs: Sequence[str] = (),
) -> ProviderPlan:
    """Build `provider`'s plan from its infra.<provider>.* APR keys via the `get` reader.

    Contract per key class: planner inputs raise when missing (a silent default would
    change what the fetcher asks the provider); leaf-native limits keep module-default
    fallbacks, logged. The per-provider validation: `request_timeout_s` must exceed
    `rate_limit_window_s` for THAT provider, because its limiter sleeps silently up to the
    window and a smaller stall bound would cancel healthy items mid-sleep.
    """

    def require(suffix: str) -> str:
        value = get(f"infra.{provider}.{suffix}")
        if value is None:
            raise RuntimeError(f"APR key infra.{provider}.{suffix} is not set")
        return value

    timeout_s = float(require(_PROVIDER_TIMEOUT_KEY))
    raw_window = get(f"infra.{provider}.{_PROVIDER_WINDOW_KEY}")
    if raw_window is None:
        # Leaf-native fallback: ibkr.py's own rate-limit window.
        window_s = 600.0
        logger.warning(
            "fetch_queue.provider_window_fallback_used",
            provider=provider,
            key=f"infra.{provider}.{_PROVIDER_WINDOW_KEY}",
        )
    else:
        window_s = float(raw_window)
    if timeout_s <= window_s:
        raise ValueError(
            f"infra.{provider}.{_PROVIDER_TIMEOUT_KEY}={timeout_s} must exceed "
            f"infra.{provider}.{_PROVIDER_WINDOW_KEY}={window_s}: the stall bound would "
            "cancel healthy items during a rate-limit sleep"
        )
    depth_overrides: dict[str, int] = {}
    for tf in depth_tfs:
        value = get(f"infra.{provider}.{_PROVIDER_DEPTH_PREFIX}{tf}")
        if value is not None:
            depth_overrides[tf] = int(value)
    return ProviderPlan(
        name=provider,
        request_timeout_s=timeout_s,
        request_retries=int(require(_PROVIDER_RETRIES_KEY)),
        rate_limit_window_s=window_s,
        confirmation_chunks=int(require(_PROVIDER_CONFIRMATION_KEY)),
        inter_item_pause_s=float(require(_PROVIDER_PAUSE_KEY)),
        answers_1d=answers_1d,
        daily_answer_filter=daily_answer_filter,
        depth_overrides=depth_overrides,
    )


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
    # The planning plane this row was read for (ohlcv_coverage.provider): failure state is
    # per-provider row state, so one vendor's outage never excludes the other vendor's items.
    provider: str = "ibkr"


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

    Known limit (2026-10-10): answered-at is a proxy for coverage here, and a run that
    plans its windows before a close then settles them after it satisfies the proxy without
    covering the close. The 1d due rule checks real window coverage (daily_due_reason); this
    shared predicate still uses the proxy for every other timeframe, where the exposure is
    the same one-session-behind shape one timing coincidence away.
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

    Provider-neutral keys fall back to the migration 432 seeds (logged when used); the ibkr
    planner inputs go through load_provider_plan and raise when missing. Malformed JSON
    raises (json.JSONDecodeError is a ValueError). history_request_timeout_s and
    history_request_retries stay on QueueConfig as fetcher-compatible mirrors of the ibkr
    plan until 190-04 passes plan instances alongside the config.
    """
    keys = list(_FALLBACKS) + list(_PROVIDER_PLAN_KEYS)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key = ANY(%s) OR config_key LIKE %s",
            (keys, _DEPTH_PREFIX + "%"),
        )
        rows = cur.fetchall()
    values = {str(k): str(v) for k, v in rows}
    missing = sorted(k for k in _FALLBACKS if k not in values)
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

    plan = load_provider_plan("ibkr", values.get, depth_tfs=tuple(_DEPTH_FALLBACKS))
    scopes = json.loads(get(_KEY_DEFAULT_SCOPES))
    return QueueConfig(
        max_consecutive_failures=int(get(_KEY_MAX_FAILURES)),
        max_staleness_days_before_preempt=int(get(_KEY_SLA_DAYS)),
        priority_tf_order=tuple(json.loads(get(_KEY_PRIORITY_TFS))),
        depth_days=depth_days,
        history_request_timeout_s=plan.request_timeout_s,
        history_request_retries=plan.request_retries,
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
class DailyAnswer:
    """A name's 1d answer state: when it was last answered, and the widest window any answer
    given since the last close covered. The due rule credits asked-since-the-close only when
    that covered window reached the close (regression 2026-10-10 and its follow-up: a
    later-answered gap-fill with an old window must not override an earlier covered answer)."""

    answered_at: datetime
    covered_window_end: datetime | None


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
    latest_answered: datetime | None,
    latest_canonical: date | None,
    rule: DailyRule,
    covered_window_end: datetime | None = None,
) -> str | None:
    """Why a name's 1d item is due, or None when it is held as current.

    - never_asked: no answered SMART TRADES 1d request exists.
    - reconcile_due: the latest answer predates rule.reconcile_after (owner rule, 185-46
      amendment B: with the interval at 1, answered before the latest completed close).
    - not_current: the latest canonical bar is not the last completed session and the name
      was not asked since that close. A name asked since the close stays held even when its
      canonical bar is stale (the freshness_1d verdict names it); re-asking it every run would
      spend the stream on an answer that already came back. Asked-since-the-close credits only
      an answer whose requested window reached the close (covered_window_end): a run spanning
      the close plans pre-close windows, and its post-close answers must not hold a stale name
      (regression 2026-10-10). Without a window end the legacy answered-at comparison stands.
    """
    if latest_answered is None:
        return "never_asked"
    if latest_answered < rule.reconcile_after:
        return "reconcile_due"
    stale = latest_canonical is None or latest_canonical < rule.last_close.date()
    if stale and latest_answered < rule.last_close:
        return "not_current"
    if stale and covered_window_end is not None and covered_window_end < rule.last_close:
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


def _depth_days(
    row: CoverageRow, config: QueueConfig, plans: Mapping[str, ProviderPlan] | None
) -> int:
    """The series' target depth: the provider's override for its own timeframes when its
    plan declares one, else the neutral map. Pure: plans enter only as data."""
    plan = (plans or {}).get(row.provider)
    if plan is not None and row.timeframe in plan.depth_overrides:
        return plan.depth_overrides[row.timeframe]
    return config.depth_days.get(row.timeframe, 0)


def _components(
    row: CoverageRow,
    proven_days: int | None,
    config: QueueConfig,
    today: date,
    plans: Mapping[str, ProviderPlan] | None = None,
) -> RankedItem:
    stale = staleness_days(row, today)
    sla_breach = stale is not None and stale > config.max_staleness_days_before_preempt
    tf_class = -1 if row.timeframe in config.priority_tf_order else 0
    target = _depth_days(row, config, plans)
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
        # the provider dimension: a final tiebreak, so the order is total across planes
        row.provider,
    )
    return RankedItem(row, key, sla_breach, tf_class, gap, stale)


def rank(
    row: CoverageRow,
    proven_days: int | None,
    config: QueueConfig,
    today: date,
    plans: Mapping[str, ProviderPlan] | None = None,
) -> tuple[Any, ...]:
    """The design tuple plus timeframe as a final element. Pure: no I/O."""
    return _components(row, proven_days, config, today, plans).rank


def queue_items(
    rows: Iterable[CoverageRow],
    config: QueueConfig,
    today: date,
    proven: Mapping[str, int] | None = None,
    plans: Mapping[str, ProviderPlan] | None = None,
) -> list[RankedItem]:
    """Non-excluded rows in rank order, with components. `proven` defaults to the depth the
    rows themselves prove; pass a mapping computed over a wider row set to rank a subset."""
    rows = list(rows)
    if proven is None:
        proven = proven_days_by_symbol(rows, today)
    items = [_components(r, proven.get(r.symbol), config, today, plans) for r in rows]
    return sorted((i for i in items if not i.rank[0]), key=lambda i: i.rank)


def order_queue(
    rows: Iterable[CoverageRow],
    config: QueueConfig,
    today: date,
    proven: Mapping[str, int] | None = None,
    plans: Mapping[str, ProviderPlan] | None = None,
) -> list[CoverageRow]:
    """Excluded rows dropped, the rest ascending by rank. Pure."""
    return [i.row for i in queue_items(rows, config, today, proven, plans)]


_COVERAGE_SQL = (
    "SELECT symbol, timeframe, provider, earliest_timestamp, latest_timestamp, "
    "last_fetch_status, consecutive_failures, last_fetched_at FROM ohlcv_coverage "
    "WHERE symbol = ANY($1::text[]) AND provider = $2"
)
_CONFIG_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])"
_HEADS_SQL = (
    "SELECT symbol, timeframe, head_ts FROM ohlcv_provider_head WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3)"
)
_EMPTY_SQL = (
    "SELECT symbol, timeframe, empty_through FROM ohlcv_empty_history WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3) "
    "AND n_confirming_chunks >= $4"
)


# The 1d due rule's first read: each name's latest answered 1d request under the provider's
# own request shape (the plan's daily_answer_filter; test callers never count, as in
# services/split_detection.py).
def _daily_answer_sql(answer_filter: str) -> str:
    # covered_window_end is the widest window among answers given since the close ($3): the due
    # rule credits asked-since-the-close only when such an answer's window reached the close.
    # A later-answered gap-fill with an old window must not override an earlier same-day
    # answer that covered it (regression follow-up, 2026-10-10).
    return (
        "SELECT symbol, max(answered_at) AS answered_at, "
        "max(window_end) FILTER (WHERE answered_at >= $3) AS covered_window_end "
        "FROM ohlcv_request "
        f"WHERE source = $1 AND timeframe = '1d' AND {answer_filter} "
        "AND outcome IN ('bars', 'no_data') AND caller NOT LIKE 'test-%' "
        "AND symbol = ANY($2::text[]) GROUP BY symbol"
    )


_LATEST_DAILY_ANSWER_SQL = _daily_answer_sql(_IBKR_DAILY_ANSWER_FILTER)
_LATEST_CANONICAL_1D_SQL = (
    'SELECT symbol, max("timestamp") AS latest FROM market_data_ohlcv_tradeable '
    "WHERE timeframe = '1d' AND symbol = ANY($1::text[]) AND \"timestamp\" >= $2 "
    "GROUP BY symbol"
)
# The span-ownership tier (migration 446): which source authors a (symbol, timeframe) span.
# The fetcher is a policy READER only - the sole writer stays scripts/ops/bars/
# ops_source_policy.py (single-writer registry) - and the read is batched over the candidate
# symbol set the way _COVERAGE_SQL batches, timeframe defaults included (symbol IS NULL).
_SOURCE_POLICY_SQL = (
    "SELECT timeframe, symbol, primary_source, fallback_source, valid_from, valid_to "
    "FROM bar_source_policy WHERE symbol = ANY($1::text[]) OR symbol IS NULL"
)
_DERIVED_SOURCE = "derived"


def policy_authorizes(
    rows: Iterable[Mapping[str, Any]], symbol: str, timeframe: str, day: date, provider: str
) -> bool:
    """True when the bar_source_policy tier lets `provider` create (or revise) items for the
    series. Pure: rows enter only as data.

    The most specific row covering `day` decides (a symbol row over the timeframe's
    NULL-symbol default; [valid_from, valid_to) half-open). The planning assignment is the
    row's authoring source: a vendor is authorized when it is named primary or fallback. A
    derived row names no fetch vendor (those bars derive from the grid source tf after the
    fetch), so it falls back to the default plane. No applicable row: today's behavior, the
    default plane authors - which with one vendor and the live row shape is a pass-through,
    the compat guarantee at this commit boundary."""
    default = default_provider()
    applicable = [
        r
        for r in rows
        if r["timeframe"] == timeframe
        and r["valid_from"] <= day
        and (r["valid_to"] is None or day < r["valid_to"])
    ]
    row = next((r for r in applicable if r["symbol"] == symbol), None)
    if row is None:
        row = next((r for r in applicable if r["symbol"] is None), None)
    if row is None or row["primary_source"] == _DERIVED_SOURCE:
        return provider == default
    return provider in (row["primary_source"], row["fallback_source"])


# Calendar slack for the canonical lookback: longer than any market closure, so a current name
# always has its latest bar inside it. A calendar fact, not a tunable.
_CANONICAL_LOOKBACK_DAYS = 14


@dataclass
class PriorityQueue:
    """The fetcher's queue over candidate series, keyed (provider, symbol, timeframe)
    internally. Legacy (symbol, timeframe) pair call shapes are accepted everywhere and
    normalized to the provider default (plan 190-03's compatibility contract: the OLD
    fetcher calls this module with pairs until 190-04).

    load() reads every ledger row of the candidate symbols for this queue's provider (all
    timeframes, so proven depth sees 1d even when 1d is out of scope) plus fresh per-TF
    provider floors; next() reloads and returns the first unvisited item. Reloading per item
    is cheap (a few thousand rows) and keeps the order in step with what the previous fetch
    just wrote.

    `current_after` (the latest completed session close) holds back series that are current
    (is_current); held_snapshot() reports them and the excluded series for the dry run.

    `plan` (a ProviderPlan) supplies the provider's budget semantics when 190-04 passes it:
    the no-data confirmation threshold, the 1d answer rule (answers_1d=False yields no
    daily-answer query and no 1d items), and per-provider depth overrides. Without it the
    queue reads the ibkr APR keys exactly as before (the old-shape path).
    """

    config: QueueConfig
    candidates: Sequence[tuple[str, ...]]
    today: date
    current_after: datetime | None = None
    # The 1d due rule (None: 1d series follow is_current like the rest, e.g. named symbols).
    daily: DailyRule | None = None
    # Per-series hold point replacing current_after (the parity sample: its ISO week start).
    current_after_by_series: Mapping[tuple[str, ...], datetime] = field(default_factory=dict)
    # This queue's planning plane when no plan is passed (the fetcher-compatible default).
    provider: str = "ibkr"
    plan: ProviderPlan | None = None
    _items: list[RankedItem] = field(default_factory=list, init=False, repr=False)
    _held: list[tuple[RankedItem, str]] = field(default_factory=list, init=False, repr=False)
    _daily_inputs: tuple[dict[str, DailyAnswer], dict[str, date]] | None = field(
        default=None, init=False, repr=False
    )
    _due_reasons: dict[tuple[str, str, str], str] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.candidates = [_series_key(c) for c in self.candidates]

    @property
    def _provider(self) -> str:
        return self.plan.name if self.plan is not None else self.provider

    @property
    def _plans(self) -> Mapping[str, ProviderPlan] | None:
        return None if self.plan is None else {self.plan.name: self.plan}

    def _hold_after(self, key: tuple[str, str, str]) -> datetime | None:
        """The series' hold point, accepting pair and triple keys in the hold map (the
        fetcher passes parity holds as pairs)."""
        if key in self.current_after_by_series:
            return self.current_after_by_series[key]
        return self.current_after_by_series.get((key[1], key[2]))

    async def load(self, pool: Any) -> None:
        symbols = sorted({s for _, s, _ in self.candidates})
        async with pool.acquire() as conn:
            reverify_days, min_confirmations = await self._load_thresholds(conn)
            coverage = await conn.fetch(_COVERAGE_SQL, symbols, self._provider)
            heads = await conn.fetch(_HEADS_SQL, self._provider, symbols, reverify_days)
            empties = await conn.fetch(
                _EMPTY_SQL, self._provider, symbols, reverify_days, min_confirmations
            )
            policy_rows = await conn.fetch(_SOURCE_POLICY_SQL, symbols)
        # Pre-465 the provider's head row has a NULL timeframe (the 1d daily-bounds
        # labeling rule); it serves every timeframe until 465 backfills it to '1d' and
        # seeds per-TF floors, after which the seeded per-TF row wins (todo 526).
        head_by_series = {(r["symbol"], r["timeframe"] or DAILY_TF): r["head_ts"] for r in heads}
        empty_by_series = {(r["symbol"], r["timeframe"]): r["empty_through"] for r in empties}

        def floor(symbol: str, timeframe: str) -> datetime | None:
            head = head_by_series.get((symbol, timeframe))
            if head is None and timeframe != DAILY_TF:
                head = head_by_series.get((symbol, DAILY_TF))
            empty = empty_by_series.get((symbol, timeframe))
            found = [ts for ts in (head, empty) if ts is not None]
            return max(found) if found else None

        all_rows = {
            (r["provider"], r["symbol"], r["timeframe"]): CoverageRow(
                symbol=r["symbol"],
                timeframe=r["timeframe"],
                earliest_timestamp=r["earliest_timestamp"],
                latest_timestamp=r["latest_timestamp"],
                last_fetch_status=r["last_fetch_status"],
                consecutive_failures=int(r["consecutive_failures"]),
                floor_timestamp=floor(r["symbol"], r["timeframe"]),
                last_fetched_at=r["last_fetched_at"],
                provider=r["provider"],
            )
            for r in coverage
        }
        proven = proven_days_by_symbol(all_rows.values(), self.today)
        candidates = [c for c in dict.fromkeys(self.candidates) if self._in_scope(c)]
        candidate_rows = [
            all_rows.get(c)
            or CoverageRow(c[1], c[2], None, None, None, 0, floor(c[1], c[2]), None, c[0])
            for c in candidates
        ]
        if self.daily is not None and self._daily_inputs is None:
            daily_symbols = sorted({s for _, s, tf in candidates if tf == DAILY_TF})
            self._daily_inputs = await self._load_daily_inputs(pool, daily_symbols)
        self._due_reasons = {}
        authorized = {
            (r.provider, r.symbol, r.timeframe): policy_authorizes(
                policy_rows, r.symbol, r.timeframe, self.today, r.provider
            )
            for r in candidate_rows
        }
        due = [
            r
            for r in candidate_rows
            if authorized[(r.provider, r.symbol, r.timeframe)] and self._is_due(r)
        ]
        self._items = queue_items(due, self.config, self.today, proven, self._plans)
        queued = {(i.row.provider, i.row.symbol, i.row.timeframe) for i in self._items}
        held = [
            (
                _components(r, proven.get(r.symbol), self.config, self.today, self._plans),
                authorized[(r.provider, r.symbol, r.timeframe)],
            )
            for r in candidate_rows
            if (r.provider, r.symbol, r.timeframe) not in queued
        ]
        self._held = sorted(
            (
                (i, "policy" if not allowed else "excluded" if i.rank[0] else "current")
                for i, allowed in held
            ),
            key=lambda pair: pair[0].rank,
        )

    def _in_scope(self, key: tuple[str, str, str]) -> bool:
        """Pitfall 4: a provider whose plan does not answer 1d never plans 1d items."""
        if self.plan is not None and not self.plan.answers_1d and key[2] == DAILY_TF:
            return False
        return True

    async def _load_thresholds(self, conn: Any) -> tuple[int, int]:
        """The floor reads' freshness age and no-data confirmation threshold. The
        confirmation threshold is the plan's when 190-04 passes one; the old-shape path
        reads the ibkr APR key and raises when missing, exactly as before."""
        cfg_rows = await conn.fetch(_CONFIG_SQL, [_REVERIFY_DAYS_KEY, _KEY_CONFIRMATION_CHUNKS])
        cfg = {r["config_key"]: r["config_value"] for r in cfg_rows}
        if _REVERIFY_DAYS_KEY not in cfg:
            raise RuntimeError(f"APR key {_REVERIFY_DAYS_KEY!r} is not set")
        if self.plan is not None:
            return int(cfg[_REVERIFY_DAYS_KEY]), self.plan.confirmation_chunks
        if _KEY_CONFIRMATION_CHUNKS not in cfg:
            raise RuntimeError(f"APR key {_KEY_CONFIRMATION_CHUNKS!r} is not set")
        return int(cfg[_REVERIFY_DAYS_KEY]), int(cfg[_KEY_CONFIRMATION_CHUNKS])

    async def _load_daily_inputs(
        self, pool: Any, symbols: list[str]
    ) -> tuple[dict[str, DailyAnswer], dict[str, date]]:
        """The 1d due rule's reads, once per queue (a run): an item fetched later in the run is
        kept out by the run's visited set, so a fresher read would change nothing."""
        if not symbols or self.daily is None or not self._answers_1d:
            return {}, {}
        since = self.daily.last_close - timedelta(days=_CANONICAL_LOOKBACK_DAYS)
        if self.plan is not None:
            answers_sql = _daily_answer_sql(self.plan.daily_answer_filter)
        else:
            answers_sql = _LATEST_DAILY_ANSWER_SQL
        async with pool.acquire() as conn:
            answers = await conn.fetch(answers_sql, self._provider, symbols, self.daily.last_close)
            canonical = await conn.fetch(_LATEST_CANONICAL_1D_SQL, symbols, since)
        return (
            {r["symbol"]: DailyAnswer(r["answered_at"], r["window_end"]) for r in answers},
            {r["symbol"]: r["latest"].astimezone(UTC).date() for r in canonical},
        )

    @property
    def _answers_1d(self) -> bool:
        return True if self.plan is None else self.plan.answers_1d

    def _is_due(self, row: CoverageRow) -> bool:
        key = (row.provider, row.symbol, row.timeframe)
        if row.timeframe == DAILY_TF and self.daily is not None and self._daily_inputs:
            if row.last_fetch_status == "error":  # never held, as is_current
                self._due_reasons[key] = "error"
                return True
            answers, canonical = self._daily_inputs
            answer = answers.get(row.symbol)
            reason = daily_due_reason(
                answer.answered_at if answer else None,
                canonical.get(row.symbol),
                self.daily,
                answer.covered_window_end if answer else None,
            )
            if reason is not None:
                self._due_reasons[key] = reason
            return reason is not None
        hold_after = self._hold_after(key)
        return not is_current(row, self.current_after if hold_after is None else hold_after)

    def due_reason(self, symbol: str, timeframe: str, provider: str | None = None) -> str:
        """Why the last load() queued a 1d series under the daily rule ('' otherwise).
        Accepts the legacy (symbol, timeframe) pair shape and the triple."""
        key = _series_key((provider, symbol, timeframe) if provider else (symbol, timeframe))
        return self._due_reasons.get(key, "")

    async def next(self, pool: Any, visited: set[tuple[str, ...]]) -> CoverageRow | None:
        """The highest-ranked item not yet visited this run (legacy pair visited keys
        accepted); None when exhausted."""
        await self.load(pool)
        seen = {_series_key(v) for v in visited}
        for item in self._items:
            if (item.row.provider, item.row.symbol, item.row.timeframe) not in seen:
                return item.row
        return None

    def ranked_snapshot(self) -> list[RankedItem]:
        """The order from the last load(), with rank tuples and components (dry run)."""
        return list(self._items)

    def held_snapshot(self) -> list[tuple[RankedItem, str]]:
        """Candidates the last load() kept out of the order, each with its reason:
        'excluded' (past the failure threshold), 'policy' (another source authors the
        span) or 'current' (is_current)."""
        return list(self._held)
