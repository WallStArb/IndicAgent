"""Record-backed gap detection for the fetch pipeline (plan 185-18 task 1a,
todo 462; design: docs/plans/2026-09-29-intraday-bar-store-redesign.md).

plan_gaps (src/intelligence/bars/gap_plan.py) is the one pure definition of a
missing bar. This module is its psycopg SQL-reading wrapper for the pipeline's
synchronous connection: it loads the stored observations (the archive for the
archive-bound 15m/1h, market_data_ohlcv for 5m, D1's ohlcv_observation for 1d),
the answered request windows, and folds in a provider-verified
ohlcv_empty_history span when it is fresh and sufficiently confirmed.
services/ cannot import from scripts/, so bar_auditor keeps its own asyncpg
readers around the same pure planner -- the SQL stays local per driver, the
rule does not.

The legacy grid-difference detect_gaps in the pipeline remains the fallback
for 1m/4h; 1d moved to D1 in task 1b.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.infrastructure.backfill._empty_history import EmptyRange
from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
    fresh_empty_span,
    plan_gaps,
)

_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60}
# Where a timeframe's stored observations live: the archive for the
# archive-bound 15m/1h (their market_data_ohlcv rows are derived cache,
# services/bar_derivation), the canonical grid table for 5m. The SQL is
# written out per table (not .format-built) so the boundary scan in
# tests/unit/test_market_data_ohlcv_boundary.py sees every raw-table read.
_ARCHIVE_SLOTS_SQL = """
SELECT timestamp FROM ohlcv_intraday_raw_archive
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s
"""
_GRID_SLOTS_SQL = """
SELECT timestamp FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s
"""
_STORED_SLOTS_SQL: dict[str, str] = {
    "5m": _GRID_SLOTS_SQL,
    "15m": _ARCHIVE_SLOTS_SQL,
    "1h": _ARCHIVE_SLOTS_SQL,
}


def _answered_windows_sql(table: str) -> str:
    return (
        """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = %s AND r.timeframe = %s AND r.route = %s AND r.what_to_show = %s
  AND r.outcome = ANY(%s) AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM """
        + table
        + """ m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m."timestamp" >= r.window_start AND m."timestamp" < r.window_end
    )
  )
ORDER BY r.window_start
"""
    )


# The corroboration subquery reads the series' own table; the literals keep
# the raw market_data_ohlcv read visible to the boundary scan.
_ANSWERED_WINDOWS_SQL: dict[str, str] = {
    "5m": _answered_windows_sql("market_data_ohlcv"),
    "15m": _answered_windows_sql("ohlcv_intraday_raw_archive"),
    "1h": _answered_windows_sql("ohlcv_intraday_raw_archive"),
}


def load_answered_windows(conn: Any, symbol: str, timeframe: str) -> AnsweredWindows:
    """Answered SMART TRADES windows for (symbol, timeframe) (todo 462).

    A `bars` answer counts only when the series' own table has a stored row in
    its window, so a failed bar insert never leaves a window that looks
    covered; `no_data` is the provider's definitive nothing-traded. timeout and
    failed outcomes never reach the window set.
    """
    sql = _ANSWERED_WINDOWS_SQL[timeframe]
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (symbol, timeframe, COVERAGE_ROUTE, COVERAGE_WHAT_TO_SHOW, list(ANSWERED_OUTCOMES)),
        )
        rows = cur.fetchall()
    return AnsweredWindows.from_rows([(r[0], r[1]) for r in rows])


def detect_gaps_from_record(
    conn: Any,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    expected_slots: Sequence[datetime],
    *,
    empty: EmptyRange | None = None,
    now: datetime | None = None,
    reverify_days: int | None = None,
    min_confirmations: int | None = None,
    on_skip: Callable[[EmptyRange], None] | None = None,
) -> list[tuple[datetime, datetime]]:
    """The gap plan for (symbol, timeframe) over [start_dt, end_dt].

    `expected_slots` come from gap_plan.expected_grid_slots. The empty-history
    gate mirrors empty_history.apply_empty_range: a range suppresses slots only
    when it is fresh (`now` within `reverify_days` of verified_at) and
    confirmed by at least `min_confirmations` chunks. When a gated range
    changes the plan, `on_skip` receives it (the pipeline prints its skip line
    and counts it there).
    """
    if timeframe not in _TF_MINUTES:
        raise ValueError(
            f"detect_gaps_from_record covers 5m/15m/1h (plan 185-18); "
            f"{timeframe!r} stays on the legacy detect_gaps fallback"
        )
    interval = timedelta(minutes=_TF_MINUTES[timeframe])
    with conn.cursor() as cur:
        cur.execute(_STORED_SLOTS_SQL[timeframe], (symbol, timeframe, start_dt, end_dt))
        rows = cur.fetchall()
    stored = [_aware(r[0]) for r in rows]
    answered = load_answered_windows(conn, symbol, timeframe)

    return _plan_with_empty_gate(
        expected_slots,
        stored,
        answered,
        interval,
        run_end=end_dt,
        empty=empty,
        now=now,
        reverify_days=reverify_days,
        min_confirmations=min_confirmations,
        on_skip=on_skip,
    )


# 1d (plan 185-18 task 1b): the answers live in D1, not in any bar table. A
# session is covered by a stored TRADES observation on its bar_date (route-
# agnostic: a former-venue recovery observation covers its session exactly
# like a SMART one, D-20), or by a definitive no_data window containing the
# whole session day. Written out per query (not .format-built) so the boundary
# scans see every raw-table read.
_1D_OBSERVED_SESSIONS_SQL = """
SELECT o.bar_date FROM ohlcv_observation o
WHERE o.symbol = %s AND o.timeframe = '1d' AND o.what_to_show = 'TRADES'
  AND o.bar_date >= %s AND o.bar_date <= %s
"""
_1D_NO_DATA_WINDOWS_SQL = """
SELECT r.window_start, r.window_end FROM ohlcv_request r
WHERE r.symbol = %s AND r.timeframe = '1d' AND r.what_to_show = 'TRADES'
  AND r.outcome = 'no_data' AND r.window_start IS NOT NULL
ORDER BY r.window_start
"""
_1D_INTERVAL = timedelta(days=1)


def midnight_utc(day: date) -> datetime:
    """A 1d slot is its session date stamped at midnight UTC (the grid's 1d
    convention); bar_date rows arrive as dates from psycopg."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _aware(ts: datetime) -> datetime:
    """psycopg naive timestamps are UTC by contract; stamp them."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def _gated_spans(
    empty: EmptyRange | None,
    now: datetime | None,
    reverify_days: int | None,
    min_confirmations: int | None,
) -> list[tuple[datetime, datetime]]:
    """The empty-history spans the shared freshness gate admits (one rule,
    gap_plan.fresh_empty_span, shared with bar_auditor and apply_empty_range)."""
    if empty is None or now is None or reverify_days is None or min_confirmations is None:
        return []
    span = fresh_empty_span(
        empty.empty_from,
        empty.empty_through,
        empty.verified_at,
        empty.n_confirming_chunks,
        now=now,
        reverify_days=reverify_days,
        min_confirmations=min_confirmations,
    )
    return [span] if span is not None else []


def _plan_with_empty_gate(
    slots: list[datetime],
    stored: list[datetime],
    answered: AnsweredWindows,
    interval: timedelta,
    *,
    run_end: datetime,
    empty: EmptyRange | None,
    now: datetime | None,
    reverify_days: int | None,
    min_confirmations: int | None,
    on_skip: Callable[[EmptyRange], None] | None,
) -> list[tuple[datetime, datetime]]:
    """plan_gaps with the shared empty-history gate folded in; `on_skip` fires
    when the gated span actually changed the plan (double-plan comparison)."""
    spans = _gated_spans(empty, now, reverify_days, min_confirmations)
    plan = plan_gaps(slots, stored, answered, interval, run_end=run_end, empty_ranges=spans)
    if spans and on_skip is not None:
        if plan_gaps(slots, stored, answered, interval, run_end=run_end) != plan:
            on_skip(empty)
    return plan


def detect_gaps_1d_from_d1(
    conn: Any,
    symbol: str,
    start: date,
    end: date,
    sessions: Mapping[date, Any],
    *,
    empty: EmptyRange | None = None,
    now: datetime | None = None,
    reverify_days: int | None = None,
    min_confirmations: int | None = None,
    on_skip: Callable[[EmptyRange], None] | None = None,
) -> list[tuple[date, date]]:
    """The 1d gap plan for `symbol` over [start, end], from D1 (task 1b).

    `sessions` is the NYSE session map (src.intelligence.bars.sessions.
    nyse_sessions) over the window; a session date whose day has no observation
    and no covering no_data window is a gap. One rule for every timeframe:
    plan_gaps with a one-day interval over session-midnight slots. Windows come
    back as contiguous end-exclusive (date, date) ranges -- the range ends at
    the last missing session's own day end, so the ask covers that whole day.

    `now` caps the horizon exactly as the intraday readers cap theirs: a
    session still forming is planned capped at now, so a no_data answer for the
    truncated window cannot cover the completed day and the next run re-asks
    it. Without `now` the horizon is the whole requested window. The
    empty-history gate mirrors detect_gaps_from_record.
    """
    if end < start:
        return []
    with conn.cursor() as cur:
        cur.execute(_1D_OBSERVED_SESSIONS_SQL, (symbol, start, end))
        observed_rows = cur.fetchall()
    with conn.cursor() as cur:
        cur.execute(_1D_NO_DATA_WINDOWS_SQL, (symbol,))
        window_rows = cur.fetchall()

    # A forming session's partial bar must not suppress its own slot: an
    # observation on bar_date == now's date was fetched mid-session (the
    # capped window asks it), and treating it as stored would pin the partial
    # bar forever -- the completed session's real bar would never be re-asked.
    # Same intent as the no_data capping in the docstring: a still-forming
    # session stays a gap until a later run sees it whole. Historical runs
    # (now=None) plan only completed sessions and keep every observation.
    forming = now.date() if now is not None else None
    stored = [midnight_utc(r[0]) for r in observed_rows if forming is None or r[0] < forming]
    answered = AnsweredWindows.from_rows((_aware(r[0]), _aware(r[1])) for r in window_rows)
    slots = [midnight_utc(day) for day in sorted(sessions) if start <= day <= end]
    run_end = now if now is not None else midnight_utc(end) + _1D_INTERVAL

    plan = _plan_with_empty_gate(
        slots,
        stored,
        answered,
        _1D_INTERVAL,
        run_end=run_end,
        empty=empty,
        now=now,
        reverify_days=reverify_days,
        min_confirmations=min_confirmations,
        on_skip=on_skip,
    )
    return [(window_start.date(), window_end.date()) for window_start, window_end in plan]


def with_overlap_window(
    gaps: Sequence[tuple[date, date]],
    sessions: Iterable[date],
    end: date,
    overlap_sessions: int,
) -> list[tuple[date, date]]:
    """`gaps` plus a window over the last `overlap_sessions` sessions up to `end`, merged (D-21).

    The nightly re-asks sessions D1 already answers so a fresh observation overlaps an
    earlier one and a split shows as a constant price ratio (services/split_detection.py).
    The planner never asks an answered session, so the overlap is added after planning, in
    the planner's own (first session, last session) window shape; windows that touch or
    overlap merge into one request. `overlap_sessions` of 0 returns the plan unchanged.
    """
    planned = list(gaps)
    if overlap_sessions <= 0:
        return planned
    eligible = sorted(day for day in sessions if day <= end)
    if not eligible:
        return planned
    windows = sorted([*planned, (eligible[-overlap_sessions:][0], eligible[-1])])
    merged: list[tuple[date, date]] = [windows[0]]
    for start, last in windows[1:]:
        prev_start, prev_last = merged[-1]
        if start <= prev_last + timedelta(days=1):
            merged[-1] = (prev_start, max(prev_last, last))
        else:
            merged.append((start, last))
    return merged
