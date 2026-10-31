"""One pure definition of a missing bar (plan 185-18 task 1a, todo 462; design:
docs/plans/2026-09-29-intraday-bar-store-redesign.md change 2).

plan_gaps is the single planner every gap consumer calls. The fetch pipeline
reads its inputs over psycopg (scripts/infrastructure/backfill/_d1_gaps.py) and
the auditor over asyncpg (services/bar_auditor.py); both feed this module, so
the fetcher and the auditor produce the same plan for the same record. A slot
is covered when:

- a stored observation exists for it (the archive for 15m/1h,
  market_data_ohlcv for 5m; the SQL readers pick the table), or
- the whole bar lies inside an answered SMART TRADES request window whose
  outcome is `bars` (corroborated by a stored row in the window, enforced in
  the loaders' SQL, so a lost insert never looks covered) or a definitive
  `no_data` (timeout and failed never cover), or -- 5m only, todo 565/567 --
  the whole bar lies inside the requested range of an applied Alpaca load (a
  SIP aggregate bar exists only where a trade printed, so a no-trade slot in
  a loaded range is the vendor's answer) or inside an answered Alpaca SIP
  5Min request window (same bars-corroborated / no_data rule), or
- its start lies inside a provider-verified ohlcv_empty_history span that is
  fresh and sufficiently confirmed (decided by fresh_empty_span below, which
  every reader calls; the SQL that loads the span stays per-driver).

Everything else is a gap. Contiguous missing slots form one end-exclusive
window: a window covering a slot ends at the slot's end, so a one-slot gap is
a request of one bar interval, never an empty window. A slot still forming
(its end after the run's end) stays a gap whose window is capped at the run's
end. A completed fetch leaves an empty plan.

Pure by construction: no connection, no clock. Datetimes arrive as data;
`run_end` is passed in. expected_grid_slots (plan 12's RTH-grid rule) lives
here too so services/ reaches it without a pipeline import.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from src.core.bar_normalizer import generate_session_slots
from src.intelligence.bars.sessions import nyse_sessions

# A request answer only covers its window when the provider definitively
# served bars (corroborated by a stored row, in the loaders' SQL) or
# definitively served nothing. timeout and failed never cover.
ANSWERED_OUTCOMES: tuple[str, ...] = ("bars", "no_data")
# The stored-bar route whose answers the coverage rule trusts (D-20: venue
# routes widen this set where venue fallback applies; 1d-only today).
COVERAGE_ROUTE = "SMART"
COVERAGE_WHAT_TO_SHOW = "TRADES"
# An applied vendor load answers every slot of the range it requested (ohlcv_load, requested_end
# inclusive). The canonical 5m vendor is Alpaca SIP, which serves a bar only for a slot in which a
# trade printed: a slot inside a successfully loaded range with no bar is the vendor's answer
# (no trade), not a gap. Only the Alpaca load whose destination is the RTH grid counts: the
# `archive` destination holds the extended-hours rows of the same ranges and says nothing about
# RTH slots. IBKR years keep the request-window rule (a stored row corroborates it); a refused or
# failed load is not an answer.
LOAD_COVERAGE_SOURCES: tuple[str, ...] = ("alpaca",)
LOAD_COVERAGE_OUTCOMES: tuple[str, ...] = ("applied",)
LOAD_COVERAGE_DESTINATIONS: tuple[str, ...] = ("market_data_ohlcv", "raw")
# Raw kinds that answer a different question than the daily TRADES bar and so never cover a 1d
# session, never move a 1d series' currency and never count in its coverage bounds: the
# dividend-adjusted series (it also holds forming bars). One definition for the planner, the
# fetch queue's currency read and the coverage ledger.
DAILY_NOT_COVERAGE_KINDS: tuple[str, ...] = ("smart_adjusted",)
# The Alpaca nightly's request rows are coverage evidence too (todo 567): source alpaca,
# route SIP, what_to_show 5Min, same bars-corroborated-or-no_data rule as the IBKR windows.
# The IEX route never counts: its rows are raw-only and never selected (todo 521). One
# (source, route, what_to_show) constant for the planner
# (scripts/infrastructure/backfill/_d1_gaps.py) and the audit
# (services/bar_reconciliation_audit.py), so both read one definition of answered, a route
# pairs with its own source and what_to_show, and no reader counts a foreign vendor's rows.
ALPACA_COVERAGE_SOURCE = "alpaca"
ALPACA_COVERAGE_ROUTE = "SIP"
ALPACA_COVERAGE_WHAT_TO_SHOW = "5Min"
COVERAGE_EVIDENCE: tuple[tuple[str, str, str], ...] = (
    ("ibkr", COVERAGE_ROUTE, COVERAGE_WHAT_TO_SHOW),
    (ALPACA_COVERAGE_SOURCE, ALPACA_COVERAGE_ROUTE, ALPACA_COVERAGE_WHAT_TO_SHOW),
)

# IBKR serves NYSE 15m/1h on its own RTH grid (a 09:30 partial 1h bar then clock hours --
# 13:30, 14:00, 15:00 UTC in summer, 14:30, 15:00, 16:00 in winter; :00/:15/:30/:45 at 15m), so
# those timeframes' expected slots are session-anchored rather than on-the-hour UTC (plan 12's
# 42-name hole). The 1h grid is verified against stored AAPL stamps on 2026-07-14, 2026-01-14
# and the 2025-11-28 half day.
_RTH_GRID_TFS = frozenset({"15m", "1h"})
_GRID_TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60}


@dataclass(frozen=True)
class AnsweredWindows:
    """Merged provider-answered request windows for one (symbol, timeframe)."""

    starts: tuple[datetime, ...] = ()
    ends: tuple[datetime, ...] = ()
    # Slots an answer served as an incomplete bar (ohlcv_request.partial_bars, migration 479):
    # never covered, whatever window holds them, so the planner asks them again.
    partial: frozenset[datetime] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.starts)

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[tuple[datetime, datetime]],
        partial: Iterable[datetime] = (),
    ) -> AnsweredWindows:
        """Merge overlapping or touching (window_start, window_end) rows."""
        merged: list[tuple[datetime, datetime]] = []
        for start, end in sorted(row for row in rows if row[1] > row[0]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return cls(tuple(s for s, _ in merged), tuple(e for _, e in merged), frozenset(partial))

    def covers(self, slot: datetime, interval: timedelta) -> bool:
        """True when the whole bar starting at `slot` lies inside a window."""
        if not self.starts or slot in self.partial:
            return False
        i = bisect_right(self.starts, slot) - 1
        return i >= 0 and slot + interval <= self.ends[i]


def load_range_windows(
    ranges: Iterable[tuple[date, date]],
) -> list[tuple[datetime, datetime]]:
    """Applied-load date ranges as (window_start, window_end) UTC datetimes for AnsweredWindows.

    `requested_end` is inclusive, so a window runs from midnight UTC of the first day to midnight
    UTC after the last. A NYSE session never crosses UTC midnight, so no slot straddles an edge.
    A day without a session holds no expected slot and so is never counted by a window.
    """
    return [
        (
            datetime.combine(first_day, time.min, tzinfo=UTC),
            datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=UTC),
        )
        for first_day, last_day in ranges
        if last_day >= first_day
    ]


def request_ts(value: datetime | str) -> datetime:
    """A request timestamp as aware UTC: naive is UTC by contract (psycopg), str is ISO."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _partial_list(value: Any) -> list[dict[str, Any]]:
    """ohlcv_request.partial_bars as a list (asyncpg returns jsonb decoded; a str is parsed)."""
    if value is None:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


def live_partials(rows: Sequence[tuple]) -> set[datetime]:
    """Slots some answer served partial and no later answer covering them served whole.

    `rows` are (window_start, window_end, partial_bars, answered_at). One rule for the planner
    (psycopg) and the audit (asyncpg), so a slot once recorded partial is re-asked until an
    answer covering it served it whole, then never again (migration 479 finding 5; third review
    of plan 191-07, low item). Moved here from _d1_gaps so the audit shares it without a
    scripts import.
    """
    marked: dict[datetime, datetime | None] = {}
    rows = list(rows)  # two passes below; a generator would exhaust on the first
    for row in rows:
        answered = request_ts(row[3]) if len(row) > 3 and row[3] is not None else None
        for bar in _partial_list(row[2]):
            ts = request_ts(bar["t"])
            prior = marked.get(ts)
            if ts not in marked or (answered is not None and (prior is None or answered > prior)):
                marked[ts] = answered
    live: set[datetime] = set()
    for ts, at in marked.items():
        cleared = at is not None and any(
            len(row) > 3
            and row[3] is not None
            and request_ts(row[3]) > at
            and request_ts(row[0]) <= ts < request_ts(row[1])
            and ts not in {request_ts(b["t"]) for b in _partial_list(row[2])}
            for row in rows
        )
        if not cleared:
            live.add(ts)
    return live


def fresh_empty_span(
    empty_from: datetime,
    empty_through: datetime,
    verified_at: datetime,
    n_confirming_chunks: int,
    *,
    now: datetime,
    reverify_days: int,
    min_confirmations: int,
) -> tuple[datetime, datetime] | None:
    """The span an ohlcv_empty_history row suppresses slots in, or None.

    One rule for every reader: a recorded span gates expected slots only
    while it is fresh (verified within `reverify_days` of `now`) and
    confirmed by at least `min_confirmations` independent provider chunks
    (a single no-data answer is not trusted, todo 049). The pipeline's
    psycopg wrappers, the auditor's asyncpg reader, and
    empty_history.apply_empty_range all decide through this function.
    """
    if n_confirming_chunks < min_confirmations:
        return None
    if now - verified_at >= timedelta(days=reverify_days):
        return None
    return (empty_from, empty_through)


@dataclass(frozen=True)
class ConfirmedSpan:
    """A span every required route answered no_data for, with the answers behind it."""

    start: datetime
    end: datetime
    n_confirming: int


def _merge_windows(
    windows: Sequence[tuple[datetime, datetime]], slack: timedelta
) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1] + slack:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _intersect_windows(
    left: Sequence[tuple[datetime, datetime]], right: Sequence[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start <= end:
            out.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return out


def confirmed_empty_spans(
    windows_by_route: Mapping[str, Sequence[tuple[datetime, datetime]]],
    required_routes: Sequence[str],
    *,
    slack: timedelta,
) -> list[ConfirmedSpan]:
    """The spans every required route answered no_data for, from one fetch run (D-20).

    `windows_by_route` holds the run's answered-empty request windows per
    route (SMART's may be a `bars` answer whose first bar lies after the span:
    the caller checks no real bar sits inside). Chunks of one route that touch within `slack` form one answered run
    (chunk boundaries sit a day apart); a span is confirmed only where every
    required route's runs overlap. A required route with no no_data window
    (a timeout or failure never is one) confirms nothing. `n_confirming` counts
    the no_data requests across the required routes that overlap the span,
    the same count the provider's walk reports as n_confirming_chunks.
    """
    if not required_routes:
        return []
    per_route: list[list[tuple[datetime, datetime]]] = []
    for route in required_routes:
        windows = windows_by_route.get(route)
        if not windows:
            return []
        per_route.append(_merge_windows(windows, slack))
    spans = per_route[0]
    for other in per_route[1:]:
        spans = _intersect_windows(spans, other)
        if not spans:
            return []
    return [
        ConfirmedSpan(
            start,
            end,
            sum(
                1
                for route in required_routes
                for w_start, w_end in windows_by_route[route]
                if w_start <= end and w_end >= start
            ),
        )
        for start, end in spans
    ]


def expected_grid_slots(
    session_id: str,
    exchange: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[datetime]:
    """Expected stored timestamps for gap detection at `timeframe`.

    15m/1h NYSE equities use IBKR's own RTH grid: a 09:30 partial 1h bar
    (13:30 UTC) then clock hours; :00/:15/:30/:45 at 15m. The old on-the-hour
    UTC generation never expected 13:30, so a missing 09:30 bar was never
    refetched (the 42-name hole the plan 12 SUMMARY records). Other session
    types and timeframes keep generate_session_slots. Moved here from the
    pipeline (plan 185-18) so services/bar_auditor reaches the same rule
    without a pipeline import.
    """
    if timeframe in _RTH_GRID_TFS and session_id == "nyse":
        return _rth_grid_slots(timeframe, start_dt, end_dt)
    return generate_session_slots(session_id, exchange, timeframe, start_dt, end_dt)


def _rth_grid_slots(timeframe: str, start_dt: datetime, end_dt: datetime) -> list[datetime]:
    """Session-anchored RTH slots for every NYSE session overlapping the window.

    15m: open-anchored, a 15 minute step. 1h: the opening bar at the session open (a 30 minute
    partial bar when the session opens at :30), then one bar per clock hour until the close;
    stepping open + n hours would expect :30 stamps IBKR never serves."""
    interval = timedelta(minutes=_GRID_TF_MINUTES[timeframe])
    sessions = nyse_sessions(start_dt.date() - timedelta(days=1), end_dt.date() + timedelta(days=1))
    slots: list[datetime] = []
    for session_open, session_close in sessions.values():
        slot = session_open
        if timeframe == "1h":
            # Subsequent bars start on the clock hour after the open.
            next_hour = session_open.replace(minute=0, second=0, microsecond=0)
            if next_hour <= session_open:
                next_hour += interval
        while slot < session_close:
            if start_dt <= slot <= end_dt:
                slots.append(slot)
            if timeframe == "1h":
                slot = next_hour
                next_hour += interval
            else:
                slot += interval
    return slots


def plan_gaps(
    slots: Iterable[datetime],
    stored: Iterable[datetime],
    answered: AnsweredWindows,
    interval: timedelta,
    *,
    run_end: datetime,
    empty_ranges: Iterable[tuple[datetime, datetime]] = (),
) -> list[tuple[datetime, datetime]]:
    """The missing-bar plan as end-exclusive (start, end) fetch windows.

    `slots` are the expected slot starts (deduplicated and sorted here);
    `stored` the observed slot timestamps; `answered` the provider-answered
    windows; `empty_ranges` the provider-verified empty spans as
    (empty_from, empty_through), covering slots whose start lies within --
    exactly the suppression the legacy subtract() applied to slot-start
    ranges. A slot whose start is at or after `run_end` is not planned; a
    planned window never ends after `run_end`, so a slot still forming stays
    a gap whose ask is capped at the run's end.
    """
    horizon = sorted({slot for slot in slots if slot < run_end})
    if not horizon:
        return []
    # A slot's end is one interval on, or the next slot's start when that comes first (a grid
    # whose opening bar is shorter than the interval: IBKR's 09:30 1h bar ends at 10:00), so a
    # request window ends where the bar ends and adjacent slots are contiguous.
    slot_end = {
        slot: min(slot + interval, following) if following > slot else slot + interval
        for slot, following in zip(horizon, [*horizon[1:], horizon[-1]], strict=True)
    }
    stored_set = set(stored)
    spans = [(empty_from, through) for empty_from, through in empty_ranges if through >= empty_from]
    missing = [
        slot
        for slot in horizon
        if slot not in stored_set
        and not answered.covers(slot, slot_end[slot] - slot)
        and not any(empty_from <= slot <= through for empty_from, through in spans)
    ]
    if not missing:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    run_start = missing[0]
    prev = missing[0]
    for slot in missing[1:]:
        if slot != slot_end[prev]:
            ranges.append((run_start, min(slot_end[prev], run_end)))
            run_start = slot
        prev = slot
    ranges.append((run_start, min(slot_end[prev], run_end)))
    return ranges
