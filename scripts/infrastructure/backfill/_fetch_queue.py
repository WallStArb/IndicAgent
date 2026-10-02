"""Deterministic priority queue for the IBKR history fetcher (phase 189 plan 02, CD-06).

The fetcher works one (symbol, timeframe) series at a time, in the order this module gives.
Ranking is a pure function of a coverage row (ohlcv_coverage, migration 432), the symbol's
proven depth, APR config and today's date, so the dry run and the real run produce the same
order. The design tuple, verbatim:

    rank(symbol, timeframe) = (
        consecutive_failures > infra.backfill.max_consecutive_failures,  -- excluded, lowest
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
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import structlog

from scripts.infrastructure.backfill._empty_history import _REVERIFY_DAYS_KEY

logger = structlog.get_logger(__name__)

PROVIDER = "ibkr"

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
    "consecutive_failures FROM ohlcv_coverage WHERE symbol = ANY($1::text[])"
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


@dataclass
class PriorityQueue:
    """The fetcher's queue over candidate (symbol, timeframe) pairs.

    load() reads every ledger row of the candidate symbols (all timeframes, so proven depth
    sees 1d even when 1d is out of scope) plus fresh provider floors; next() reloads and
    returns the first unvisited item. Reloading per item is cheap (a few thousand rows) and
    keeps the order in step with what the previous fetch just wrote.
    """

    config: QueueConfig
    candidates: Sequence[tuple[str, str]]
    today: date
    _items: list[RankedItem] = field(default_factory=list, init=False, repr=False)

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
            )
            for r in coverage
        }
        proven = proven_days_by_symbol(all_rows.values(), self.today)
        candidate_rows = [
            all_rows.get((s, tf)) or CoverageRow(s, tf, None, None, None, 0, floor(s, tf))
            for s, tf in dict.fromkeys(self.candidates)
        ]
        self._items = queue_items(candidate_rows, self.config, self.today, proven)

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
