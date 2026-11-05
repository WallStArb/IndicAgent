"""The corpus rerun data gate (186-32, todo 593; the 584 rule, owner and lead 2026-11-04).

No corpus compute runs until every compute_1d name's history is continuous: for each name and
year, every exchange-calendar session from the name's proven start to the horizon holds a
tradeable 1d bar and 5m coverage from the policy primary of its era, within the APR tolerances.
Continuity, not the earliest row: a name whose first 5m bar sits at its 1d start but with a hole
mid-history fails.

- Sessions are the exchange calendar's, keyed by contract_details session_id (resolved as
  src/core/bar_normalizer.py resolves it, never the contract's exchange, which is SMART for every
  name), from max(proven start, the calendar's first session) to the horizon, so the 1d and 5m
  checks share one session list and a missing 1d bar cannot hide a missing 5m session. 1d bars
  before the calendar's first session are counted per name, never dropped unreported.
- The 5m (vendor, kind) of a session is its bar_source_policy_current primary (a symbol row beats
  the default) mapped through daily_rule.primary_pair with the Alpaca 5m era start read from the
  policy. A session is covered when its in-session bars reach
  infra.corpus_rerun.data_gate.min_session_bar_fraction of its own expected slots (its own open
  to close, so half days are shorter) or when it lies inside an ohlcv_empty_history span of that
  vendor; some bars below the fraction is partial, none is missing.
- A name with no proven start, no session, or no tradeable 1d session fails, unless the one
  recorded rule holds it: 1d empty-history spans of each 1d policy era's primary provider cover
  every calendar session from the calendar's first session to the horizon.

The fetch layer is set-based SQL (one 5m query per (vendor, kind), no per-name loop); `evaluate`
is pure. Nothing is written: the step runner (186-31) persists the result to corpus_run.
"""

from __future__ import annotations

import bisect
import time
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog

from services.backfill_feature_factory import (
    _filter_etf_contracts,
    default_data_horizon,
    proven_starts,
)
from services.corpus_rerun_apr import CorpusRerunApr
from src.config.settings import Settings, get_active_contracts
from src.core.market_calendar import MarketCalendar, get_market_calendar
from src.intelligence.bars.daily_rule import PolicyRow, primary_pair
from src.intelligence.bars.vendor_kind import VENDOR_ALPACA, VENDOR_IBKR

_logger = structlog.get_logger(__name__)

TF_5M = "5m"
TF_1D = "1d"
_SLOT = timedelta(minutes=5)

# contract_details session_id -> calendar key, as src/core/bar_normalizer.py resolves it (session
# 'nyse' is judged on the NYSE calendar). A session_id outside this map has no calendar here.
SESSION_CALENDAR: dict[str, str] = {"nyse": "NYSE"}

COVERED_5M = "covered_5m"
COVERED_EMPTY = "covered_empty"
PARTIAL = "partial"

SURVIVORSHIP_CAVEAT_CODE = "survivorship_pre2016_ibkr_5m"
SURVIVORSHIP_CAVEAT_SOURCE = "todo 534 owner decision 2026-11-04"
SURVIVORSHIP_CAVEAT_TEXT = (
    "IBKR serves only names that trade today and the universe was chosen today, so every result "
    "whose sample includes pre-2016 5m is survivorship-biased."
)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    day: date
    open: datetime
    close: datetime

    @property
    def expected_slots(self) -> float:
        return (self.close - self.open) / _SLOT


@dataclass(frozen=True)
class Segment:
    """A run of one name's sessions [lo, hi) whose 5m primary serves under one (vendor, kind)."""

    lo: date
    hi: date
    vendor: str
    kind: str

    @property
    def era(self) -> str:
        return era_label(self.vendor, self.kind)


@dataclass(frozen=True)
class EmptySpan:
    """One ohlcv_empty_history row; it answers the sessions from verified_from through
    empty_through (UTC dates, inclusive), as the 1d verdict audit reads it."""

    symbol: str
    timeframe: str
    provider: str
    empty_from: date
    verified_from: date
    empty_through: date

    def covers(self, day: date) -> bool:
        return self.verified_from <= day <= self.empty_through


@dataclass
class NameYearTally:
    """Session counts of one (symbol, year, era). Before the 5m rows stream in, every session
    inside an empty-history span is counted as covered_empty (the assumption of no bars); a
    streamed row replaces that assumption with its own class."""

    sessions: int = 0
    with_1d: int = 0
    covered_5m: int = 0
    covered_empty: int = 0
    partial: int = 0

    @property
    def missing(self) -> int:
        return self.sessions - self.covered_5m - self.covered_empty - self.partial

    @property
    def uncovered(self) -> int:
        return self.partial + self.missing


TallyKey = tuple[str, int, str]  # (symbol, year, era)


@dataclass
class EraCounts:
    names: int = 0
    names_at_depth: int = 0
    names_partial: int = 0
    names_none: int = 0
    name_years: int = 0
    failing_name_years: int = 0
    sessions: int = 0
    sessions_with_1d: int = 0
    covered_5m: int = 0
    covered_empty: int = 0
    partial_sessions: int = 0
    missing_sessions: int = 0


@dataclass(frozen=True)
class FailingNameYear:
    symbol: str
    year: int
    sessions: int
    missing_1d: int
    partial_5m: int
    missing_5m: int


@dataclass(frozen=True)
class DataGateResult:
    ok: bool
    horizon: datetime
    calendar_key: str
    calendar_first_session: date
    alpaca_5m_era_start: date
    thresholds: dict[str, float]
    names_checked: int
    eras: dict[str, EraCounts]
    names_without_proven_start: tuple[str, ...]
    names_with_zero_sessions: tuple[str, ...]
    names_with_zero_1d_sessions: tuple[str, ...]
    held_names: dict[str, tuple[EmptySpan, ...]]
    failing_name_years: tuple[FailingNameYear, ...]
    pre_calendar_1d_sessions: dict[str, int]
    pre_calendar_1d_sessions_total: int
    caveat: dict[str, Any] | None = None

    def as_record(self) -> dict[str, Any]:
        """The JSON-safe record the runner stores in corpus_run.data_gate."""
        record: dict[str, Any] = _json_safe(asdict(self))
        return record


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, date):  # datetime is a date
        return value.isoformat()
    return value


def era_label(vendor: str, kind: str) -> str:
    return f"{vendor}/{kind}"


# ---------------------------------------------------------------------------
# Calendar and policy (pure)
# ---------------------------------------------------------------------------


def resolve_calendar_key(universe: Sequence[Any], calendar: MarketCalendar) -> str:
    """The one calendar key the universe's session_ids resolve to. Raises, listing each name, on
    a session_id the calendar does not support (no partial gate), and on an empty universe (a
    gate over no names would pass vacuously)."""
    if not universe:
        raise ValueError("data gate: the compute_1d universe is empty")
    keys: set[str] = set()
    unsupported: list[str] = []
    for contract in universe:
        key = SESSION_CALENDAR.get(contract.session_id)
        if key is None or not calendar.supports_exchange(key):
            unsupported.append(f"{contract.symbol} (session_id {contract.session_id!r})")
        else:
            keys.add(key)
    if unsupported:
        raise ValueError(
            "data gate: no supported calendar for session_id of "
            f"{len(unsupported)} names: {', '.join(unsupported)}"
        )
    if len(keys) != 1:
        raise ValueError(f"data gate: one calendar per gate, the universe resolves to {keys}")
    return keys.pop()


def calendar_sessions(calendar: MarketCalendar, key: str, horizon: datetime) -> list[Session]:
    """The calendar's sessions from its first session that close at or before the horizon."""
    sessions: list[Session] = []
    day = calendar.first_session(key)
    while day <= horizon.date():
        if calendar.is_trading_day(key, day):
            open_ts, close_ts = calendar.session_bounds(key, day)
            if close_ts <= horizon:
                sessions.append(Session(day, open_ts.to_pydatetime(), close_ts.to_pydatetime()))
        day += timedelta(days=1)
    return sessions


def _policy_at(rows: Sequence[PolicyRow], symbol: str, day: date) -> PolicyRow:
    covering = [r for r in rows if r.covers(day)]
    for scope in (symbol, None):
        matched = [r for r in covering if r.symbol == scope]
        if len(matched) > 1:
            raise LookupError(f"bar_source_policy rows overlap for ({scope}) on {day}")
        if matched:
            return matched[0]
    raise LookupError(f"no bar_source_policy row covers {symbol} on {day}")


def policy_segments(
    rows: Sequence[PolicyRow], symbol: str, lo: date, hi: date, split_at: Iterable[date] = ()
) -> list[tuple[date, date, PolicyRow]]:
    """[lo, hi) cut where any policy row of the name (or the default) starts or ends, and at
    `split_at`; each piece with the row that governs it (a symbol row beats the default)."""
    cuts = {lo, hi, *split_at}
    for r in rows:
        if r.symbol in (None, symbol):
            cuts.add(r.valid_from)
            if r.valid_to is not None:
                cuts.add(r.valid_to)
    bounds = sorted(c for c in cuts if lo <= c <= hi)
    return [(a, b, _policy_at(rows, symbol, a)) for a, b in zip(bounds, bounds[1:], strict=False)]


def alpaca_5m_era_start(rows_5m: Sequence[PolicyRow]) -> date:
    """valid_from of the default 5m policy row whose primary is Alpaca."""
    starts = [
        r.valid_from for r in rows_5m if r.symbol is None and r.primary_source == VENDOR_ALPACA
    ]
    if len(starts) != 1:
        raise LookupError(f"expected one default 5m Alpaca policy row, found {len(starts)}")
    return starts[0]


def five_minute_segments(
    rows_5m: Sequence[PolicyRow], symbol: str, lo: date, hi: date, era_start: date
) -> list[Segment]:
    """The name's [lo, hi) by the (vendor, kind) its 5m primary serves under."""
    segments: list[Segment] = []
    for a, b, row in policy_segments(rows_5m, symbol, lo, hi, split_at=(era_start,)):
        vendor, kind = primary_pair(row.primary_source, a, era_start)
        if segments and segments[-1] == Segment(segments[-1].lo, a, vendor, kind):
            segments[-1] = Segment(segments[-1].lo, b, vendor, kind)
        else:
            segments.append(Segment(a, b, vendor, kind))
    return segments


def _sessions_in(days: Sequence[date], lo: date, hi_inclusive: date) -> int:
    return bisect.bisect_right(days, hi_inclusive) - bisect.bisect_left(days, lo)


def hold_spans(
    rows_1d: Sequence[PolicyRow],
    symbol: str,
    days: Sequence[date],
    spans_1d: Mapping[tuple[str, str], Sequence[EmptySpan]],
) -> tuple[EmptySpan, ...] | None:
    """The one recorded hold: 1d empty-history spans whose provider is the 1d policy primary of
    the era they answer, together covering every calendar session in `days`. Returns the spans
    used, or None (a span of another provider holds nothing)."""
    if not days:
        return None
    used: list[EmptySpan] = []
    for lo, hi, row in policy_segments(rows_1d, symbol, days[0], days[-1] + timedelta(days=1)):
        segment_days = days[bisect.bisect_left(days, lo) : bisect.bisect_left(days, hi)]
        if not segment_days:
            continue
        spans = spans_1d.get((symbol, row.primary_source), ())
        if not all(any(s.covers(d) for s in spans) for d in segment_days):
            return None
        used.extend(s for s in spans if s not in used)
    return tuple(used)


# ---------------------------------------------------------------------------
# Tallies (pure)
# ---------------------------------------------------------------------------


def classify_session(bars: int, expected_slots: float, fraction: float, in_span: bool) -> str:
    """A session with bars: covered by 5m when its bars reach `fraction` of its expected slots,
    else covered by the empty-history answer when inside a span, else partial."""
    if bars >= fraction * expected_slots:
        return COVERED_5M
    return COVERED_EMPTY if in_span else PARTIAL


def session_tallies(
    segments: Mapping[str, Sequence[Segment]],
    days: Sequence[date],
    spans_5m: Mapping[tuple[str, str], Sequence[EmptySpan]],
) -> dict[TallyKey, NameYearTally]:
    """Sessions per (symbol, year, era), with every in-span session counted covered_empty.
    ohlcv_empty_history holds one row per (symbol, timeframe, provider), so spans never
    overlap and no session is counted twice."""
    tallies: dict[TallyKey, NameYearTally] = defaultdict(NameYearTally)
    for symbol, name_segments in segments.items():
        for seg in name_segments:
            spans = spans_5m.get((symbol, seg.vendor), ())
            last = seg.hi - timedelta(days=1)
            for year in range(seg.lo.year, last.year + 1):
                lo = max(seg.lo, date(year, 1, 1))
                hi = min(last, date(year, 12, 31))
                n = _sessions_in(days, lo, hi)
                if n == 0:
                    continue
                tally = tallies[(symbol, year, seg.era)]
                tally.sessions += n
                for span in spans:
                    a, b = max(lo, span.verified_from), min(hi, span.empty_through)
                    if a <= b:
                        tally.covered_empty += _sessions_in(days, a, b)
    return dict(tallies)


def record_session_bars(
    tallies: Mapping[TallyKey, NameYearTally],
    era: str,
    vendor: str,
    rows: Iterable[tuple[str, date, int]],
    sessions_by_day: Mapping[date, Session],
    spans_5m: Mapping[tuple[str, str], Sequence[EmptySpan]],
    fraction: float,
) -> None:
    """Fold one (vendor, kind)'s (symbol, session day, in-session bar count) rows into the
    tallies."""
    for symbol, day, bars in rows:
        tally = tallies[(symbol, day.year, era)]
        in_span = any(s.covers(day) for s in spans_5m.get((symbol, vendor), ()))
        if in_span:
            tally.covered_empty -= 1
        kind = classify_session(bars, sessions_by_day[day].expected_slots, fraction, in_span)
        setattr(tally, kind, getattr(tally, kind) + 1)


# ---------------------------------------------------------------------------
# Evaluate (pure)
# ---------------------------------------------------------------------------


def evaluate(
    tallies: Mapping[TallyKey, NameYearTally],
    universe: Sequence[str],
    starts: Mapping[str, date],
    holds: Mapping[str, tuple[EmptySpan, ...]],
    pre_calendar: Mapping[str, int],
    apr: CorpusRerunApr,
    *,
    horizon: datetime,
    calendar_key: str,
    first_session: date,
    era_start: date,
) -> DataGateResult:
    """Judge the tallies. A name without a start, sessions or 1d sessions refuses unless held;
    a name-year fails when its 1d-missing or 5m-uncovered share of sessions passes its APR
    tolerance. On a pass the result carries the survivorship caveat with its counts."""
    by_name: dict[str, dict[TallyKey, NameYearTally]] = defaultdict(dict)
    for key, tally in tallies.items():
        by_name[key[0]][key] = tally

    without_start = sorted(s for s in universe if s not in starts)
    zero_sessions = sorted(s for s in universe if s in starts and not by_name.get(s))
    zero_1d = sorted(
        s for s in universe if by_name.get(s) and not any(t.with_1d for t in by_name[s].values())
    )
    refused_or_held = set(without_start) | set(zero_sessions) | set(zero_1d)
    held = {s: holds[s] for s in sorted(refused_or_held) if s in holds}
    refused = refused_or_held - set(held)

    tol_5m = apr.max_missing_session_fraction
    tol_1d = apr.max_missing_1d_session_fraction
    eras: dict[str, EraCounts] = defaultdict(EraCounts)
    failing: list[FailingNameYear] = []
    for symbol in sorted(set(by_name) - refused_or_held):
        name_eras: dict[str, NameYearTally] = defaultdict(NameYearTally)
        years: dict[int, list[tuple[str, NameYearTally]]] = defaultdict(list)
        for (_, year, era), t in by_name[symbol].items():
            years[year].append((era, t))
            total = name_eras[era]
            for f in ("sessions", "with_1d", "covered_5m", "covered_empty", "partial"):
                setattr(total, f, getattr(total, f) + getattr(t, f))
        for era, t in name_eras.items():
            counts = eras[era]
            counts.names += 1
            if t.uncovered <= tol_5m * t.sessions:
                counts.names_at_depth += 1
            elif t.covered_5m == 0:
                counts.names_none += 1
            else:
                counts.names_partial += 1
            counts.sessions += t.sessions
            counts.sessions_with_1d += t.with_1d
            counts.covered_5m += t.covered_5m
            counts.covered_empty += t.covered_empty
            counts.partial_sessions += t.partial
            counts.missing_sessions += t.missing
        for year, parts in sorted(years.items()):
            sessions = sum(t.sessions for _, t in parts)
            missing_1d = sessions - sum(t.with_1d for _, t in parts)
            partial = sum(t.partial for _, t in parts)
            missing = sum(t.missing for _, t in parts)
            fails = missing_1d > tol_1d * sessions or partial + missing > tol_5m * sessions
            for era, _ in parts:
                eras[era].name_years += 1
                eras[era].failing_name_years += fails
            if fails:
                failing.append(
                    FailingNameYear(symbol, year, sessions, missing_1d, partial, missing)
                )

    ok = not refused and not failing
    pre_calendar_nonzero = {s: n for s, n in sorted(pre_calendar.items()) if n}
    return DataGateResult(
        ok=ok,
        horizon=horizon,
        calendar_key=calendar_key,
        calendar_first_session=first_session,
        alpaca_5m_era_start=era_start,
        thresholds={
            "max_missing_session_fraction": tol_5m,
            "max_missing_1d_session_fraction": tol_1d,
            "min_session_bar_fraction": apr.min_session_bar_fraction,
        },
        names_checked=len(universe),
        eras=dict(sorted(eras.items())),
        names_without_proven_start=tuple(without_start),
        names_with_zero_sessions=tuple(zero_sessions),
        names_with_zero_1d_sessions=tuple(zero_1d),
        held_names=held,
        failing_name_years=tuple(failing),
        pre_calendar_1d_sessions=pre_calendar_nonzero,
        pre_calendar_1d_sessions_total=sum(pre_calendar_nonzero.values()),
        caveat=(
            _survivorship_caveat(
                {k: t for k, t in tallies.items() if k[0] not in refused_or_held}, era_start
            )
            if ok
            else None
        ),
    )


def _survivorship_caveat(
    tallies: Mapping[TallyKey, NameYearTally], era_start: date
) -> dict[str, Any]:
    """The pre-2016 IBKR 5m caveat over the sessions IBKR serves as primary before the Alpaca
    era."""
    pre_era = era_label(*primary_pair(VENDOR_IBKR, era_start - timedelta(days=1), era_start))
    per_name: dict[str, NameYearTally] = defaultdict(NameYearTally)
    for (symbol, _, era), t in tallies.items():
        if era == pre_era:
            total = per_name[symbol]
            total.sessions += t.sessions
            total.covered_5m += t.covered_5m
            total.covered_empty += t.covered_empty
    return {
        "code": SURVIVORSHIP_CAVEAT_CODE,
        "source": SURVIVORSHIP_CAVEAT_SOURCE,
        "text": SURVIVORSHIP_CAVEAT_TEXT,
        "counts": {
            "names_with_1d_before_alpaca_era": len(per_name),
            "names_pre_era_all_5m": sum(t.covered_5m == t.sessions for t in per_name.values()),
            "names_pre_era_partly_empty_history": sum(
                t.covered_empty > 0 for t in per_name.values()
            ),
            "pre_era_sessions_by_5m": sum(t.covered_5m for t in per_name.values()),
            "pre_era_sessions_by_empty_history": sum(t.covered_empty for t in per_name.values()),
        },
    }


# ---------------------------------------------------------------------------
# Fetch layer (set-based SQL, reads only)
# ---------------------------------------------------------------------------

_POLICY_SQL = """
SELECT timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source
FROM bar_source_policy_current WHERE timeframe = %s
"""

_EMPTY_SPANS_SQL = """
SELECT symbol, timeframe, provider, (empty_from AT TIME ZONE 'UTC')::date,
       (verified_from AT TIME ZONE 'UTC')::date, (empty_through AT TIME ZONE 'UTC')::date
FROM ohlcv_empty_history WHERE timeframe = %s
"""

# Sessions of each name's segments that hold a tradeable 1d bar (1d bars stamp 00:00 UTC).
_1D_COUNTS_SQL = """
WITH seg AS (
    SELECT * FROM unnest(%(symbols)s::text[], %(los)s::date[], %(his)s::date[], %(eras)s::text[])
        AS g(symbol, lo, hi, era)
), cal AS (SELECT unnest(%(days)s::date[]) AS day),
bar AS (
    SELECT DISTINCT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS day
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = %(tf)s AND symbol = ANY(%(names)s) AND "timestamp" < %(horizon)s
)
SELECT g.symbol, extract(year FROM b.day)::int, g.era, count(*)::int
FROM bar b JOIN cal c ON c.day = b.day
JOIN seg g ON g.symbol = b.symbol AND b.day >= g.lo AND b.day < g.hi
GROUP BY 1, 2, 3
"""

_PRE_CALENDAR_SQL = """
SELECT symbol, count(DISTINCT ("timestamp" AT TIME ZONE 'UTC')::date)::int
FROM market_data_ohlcv_tradeable
WHERE timeframe = %(tf)s AND symbol = ANY(%(names)s) AND "timestamp" < %(first)s
GROUP BY 1
"""

# In-session 5m bars of one (vendor, kind) per (symbol, session) over each name's segments of it.
_5M_SESSION_BARS_SQL = """
WITH seg AS (
    SELECT * FROM unnest(%(symbols)s::text[], %(los)s::date[], %(his)s::date[])
        AS g(symbol, lo, hi)
), cal AS (
    SELECT * FROM unnest(%(days)s::date[], %(opens)s::timestamptz[], %(closes)s::timestamptz[])
        AS c(day, open_ts, close_ts)
)
SELECT r.symbol, c.day, count(*)::int
FROM ohlcv_raw r
JOIN cal c ON c.day = (r."timestamp" AT TIME ZONE 'UTC')::date
          AND r."timestamp" >= c.open_ts AND r."timestamp" < c.close_ts
JOIN seg g ON g.symbol = r.symbol AND c.day >= g.lo AND c.day < g.hi
WHERE r.timeframe = %(tf)s AND r.vendor = %(vendor)s AND r.kind = %(kind)s
  AND r.symbol = ANY(%(names)s) AND r."timestamp" >= %(ts_lo)s AND r."timestamp" < %(ts_hi)s
GROUP BY r.symbol, c.day
"""


def fetch_policy(conn: Any, timeframe: str) -> list[PolicyRow]:
    with conn.cursor() as cur:
        cur.execute(_POLICY_SQL, (timeframe,))
        return [PolicyRow(*row) for row in cur.fetchall()]


def fetch_empty_spans(conn: Any, timeframe: str) -> dict[tuple[str, str], tuple[EmptySpan, ...]]:
    spans: dict[tuple[str, str], list[EmptySpan]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(_EMPTY_SPANS_SQL, (timeframe,))
        for row in cur.fetchall():
            span = EmptySpan(*row)
            spans[(span.symbol, span.provider)].append(span)
    return {key: tuple(value) for key, value in spans.items()}


def _segment_arrays(segments: Mapping[str, Sequence[Segment]]) -> dict[str, list[Any]]:
    flat = [(s, seg) for s, segs in segments.items() for seg in segs]
    return {
        "symbols": [s for s, _ in flat],
        "los": [seg.lo for _, seg in flat],
        "his": [seg.hi for _, seg in flat],
        "eras": [seg.era for _, seg in flat],
    }


def fetch_1d_counts(
    conn: Any, segments: Mapping[str, Sequence[Segment]], days: Sequence[date], horizon: datetime
) -> dict[TallyKey, int]:
    with conn.cursor() as cur:
        cur.execute(
            _1D_COUNTS_SQL,
            {
                **_segment_arrays(segments),
                "days": list(days),
                "tf": TF_1D,
                "names": sorted(segments),
                "horizon": horizon,
            },
        )
        return {(s, y, e): n for s, y, e, n in cur.fetchall()}


def fetch_pre_calendar_1d(conn: Any, names: Sequence[str], first_session: date) -> dict[str, int]:
    """Tradeable 1d sessions before the calendar's first session, per name, from the start of its
    series: every proven start is at or after the first session (the 1d verdict judges from it),
    so counting from the start would report none of these bars."""
    with conn.cursor() as cur:
        cur.execute(
            _PRE_CALENDAR_SQL,
            {
                "names": list(names),
                "tf": TF_1D,
                "first": datetime.combine(first_session, datetime.min.time(), tzinfo=UTC),
            },
        )
        return dict(cur.fetchall())


def iter_5m_session_bars(
    conn: Any,
    vendor: str,
    kind: str,
    segments: Mapping[str, Sequence[Segment]],
    sessions: Sequence[Session],
) -> Iterator[tuple[str, date, int]]:
    """(symbol, session day, in-session bar count) for every session of the names' segments of
    (vendor, kind) that holds any bar of it; streamed, never one corpus frame."""
    pair_segments = {
        s: [seg for seg in segs if (seg.vendor, seg.kind) == (vendor, kind)]
        for s, segs in segments.items()
    }
    pair_segments = {s: segs for s, segs in pair_segments.items() if segs}
    if not pair_segments:
        return
    arrays = _segment_arrays(pair_segments)
    del arrays["eras"]
    lo, hi = min(arrays["los"]), max(arrays["his"])
    in_range = [x for x in sessions if lo <= x.day < hi]
    with conn.cursor() as cur:
        yield from cur.stream(
            _5M_SESSION_BARS_SQL,
            {
                **arrays,
                "days": [x.day for x in in_range],
                "opens": [x.open for x in in_range],
                "closes": [x.close for x in in_range],
                "tf": TF_5M,
                "vendor": vendor,
                "kind": kind,
                "names": sorted(pair_segments),
                "ts_lo": datetime.combine(lo, datetime.min.time(), tzinfo=UTC),
                "ts_hi": datetime.combine(hi, datetime.min.time(), tzinfo=UTC),
            },
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_data_gate(
    conn: Any,
    settings: Settings,
    apr: CorpusRerunApr,
    *,
    horizon: datetime | None = None,
    calendar: MarketCalendar | None = None,
) -> DataGateResult:
    """Measure the compute_1d universe (the rebuild's own) against the 584 rule. Reads only."""
    started = time.monotonic()
    horizon = horizon or default_data_horizon()
    if horizon.tzinfo is None:
        raise ValueError("run_data_gate: horizon must be tz-aware")
    calendar = calendar or get_market_calendar()
    universe = _filter_etf_contracts(get_active_contracts(settings, dimension="compute_1d"), None)
    key = resolve_calendar_key(universe, calendar)
    names = sorted({c.symbol for c in universe})
    starts = {s: ts.date() for s, ts in proven_starts(conn, names).items()}

    first = calendar.first_session(key)
    sessions = calendar_sessions(calendar, key, horizon)
    days = [x.day for x in sessions]
    end = days[-1] + timedelta(days=1) if days else first
    rows_5m, rows_1d = fetch_policy(conn, TF_5M), fetch_policy(conn, TF_1D)
    era_start = alpaca_5m_era_start(rows_5m)
    segments = {
        s: five_minute_segments(rows_5m, s, max(start, first), end, era_start)
        for s, start in starts.items()
        if max(start, first) < end
    }
    spans_5m, spans_1d = fetch_empty_spans(conn, TF_5M), fetch_empty_spans(conn, TF_1D)

    tallies = session_tallies(segments, days, spans_5m)
    for tally_key, n in fetch_1d_counts(conn, segments, days, horizon).items():
        tallies[tally_key].with_1d = n
    sessions_by_day = {x.day: x for x in sessions}
    pairs = sorted({(seg.vendor, seg.kind) for segs in segments.values() for seg in segs})
    for vendor, kind in pairs:
        rows = iter_5m_session_bars(conn, vendor, kind, segments, sessions)
        record_session_bars(
            tallies,
            era_label(vendor, kind),
            vendor,
            rows,
            sessions_by_day,
            spans_5m,
            apr.min_session_bar_fraction,
        )

    holds = {
        s: spans
        for s in names
        if any(k[0] == s for k in spans_1d) and (spans := hold_spans(rows_1d, s, days, spans_1d))
    }
    pre_calendar = fetch_pre_calendar_1d(conn, names, first)
    result = evaluate(
        tallies,
        names,
        starts,
        holds,
        pre_calendar,
        apr,
        horizon=horizon,
        calendar_key=key,
        first_session=first,
        era_start=era_start,
    )
    _logger.info(
        "corpus_rerun_data_gate.measured",
        ok=result.ok,
        names=result.names_checked,
        failing_name_years=len(result.failing_name_years),
        refused=len(result.names_without_proven_start)
        + len(result.names_with_zero_sessions)
        + len(result.names_with_zero_1d_sessions)
        - len(result.held_names),
        seconds=round(time.monotonic() - started, 1),
    )
    return result
