"""Record-backed gap detection for the fetch pipeline (plan 185-18 task 1a,
todo 462; design: docs/plans/2026-09-29-intraday-bar-store-redesign.md).

plan_gaps (src/intelligence/bars/gap_plan.py) is the one pure definition of a
missing bar. This module is its psycopg SQL-reading wrapper for the pipeline's
synchronous connection. Raw is stored per source, agnostic to every other source, so
the one question here is: for THIS vendor, which slots of [A, B] are missing from its
own ohlcv_raw rows, minus its own answered request windows (a definitive no_data
included)? Every read is filtered by `vendor`; another vendor's rows, answers and
canonical selection never cover a slot. The wrapper also folds in a provider-verified
ohlcv_empty_history span when it is fresh and sufficiently confirmed.
services/ cannot import from scripts/, so bar_auditor keeps its own asyncpg
readers around the same pure planner -- the SQL stays local per driver, the
rule does not.

The legacy grid-difference detect_gaps in the pipeline remains the fallback
for 1m/4h; 1d moved to D1 in task 1b.
"""

from __future__ import annotations

import json
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
    DAILY_NOT_COVERAGE_KINDS,
    AnsweredWindows,
    fresh_empty_span,
    plan_gaps,
)
from src.intelligence.bars.sessions import session_complete_at
from src.intelligence.bars.vendor_kind import VENUE_ROUTES

_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60}
# Every intraday slot this vendor holds, whatever the kind (an intraday series has one kind per
# vendor today; a second would still be the same vendor's slot).
_RAW_SLOTS_SQL = """
SELECT DISTINCT "timestamp" FROM ohlcv_raw
WHERE symbol = %s AND timeframe = %s AND vendor = %s AND "timestamp" >= %s AND "timestamp" <= %s
"""
# The one answered-window read for every timeframe (todo 527's five copies). A `bars` answer
# counts only when this vendor holds a raw row in its window (a lost insert never looks
# covered); `no_data` is the provider's definitive nothing-traded. timeout and failed never
# reach the set.
#
# A `bars` answer whose load the contract refused is no answer (third review of plan 191-07,
# finding 3): its offer is held or lost, so counting its window as answered would leave the
# vendor's slots a permanent silent hole. A load persists the latest request of its series
# answered at or before it, at most infra.selection_gate.request_load_match_s seconds earlier
# (the retired path wrote no request id on the load; ops_selection_gate.match_requests).
_ANSWERED_WINDOWS_SQL = """
SELECT r.window_start, r.window_end, r.partial_bars, r.answered_at
FROM ohlcv_request r
WHERE r.symbol = %(symbol)s AND r.timeframe = %(timeframe)s AND r.source = %(vendor)s
  AND r.what_to_show = %(what)s AND r.route = ANY(%(routes)s) AND r.outcome = ANY(%(outcomes)s)
  AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM ohlcv_raw m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe AND m.vendor = r.source
        AND m."timestamp" >= r.window_start AND m."timestamp" < r.window_end
    )
  )
  AND NOT EXISTS (
    SELECT 1 FROM ohlcv_load l
    WHERE l.symbol = r.symbol AND l.timeframe = r.timeframe AND l.source = r.source
      AND l.outcome = 'refused' AND l.loaded_at >= r.answered_at
      AND l.loaded_at <= r.answered_at + make_interval(secs => %(match_s)s)
      AND NOT EXISTS (
        SELECT 1 FROM ohlcv_request q
        WHERE q.symbol = r.symbol AND q.timeframe = r.timeframe AND q.source = r.source
          AND q.answered_at > r.answered_at AND q.answered_at <= l.loaded_at
      )
  )
ORDER BY r.window_start
"""
MATCH_S_KEY = "infra.selection_gate.request_load_match_s"
_MATCH_S_SQL = "SELECT config_value FROM config_state WHERE config_key = %s"
# Intraday answers are SMART TRADES requests; the daily no_data question is asked on SMART and
# every former-venue route (D-20), and only a definitive nothing-traded covers a daily session.
_INTRADAY_ROUTES: tuple[str, ...] = (COVERAGE_ROUTE,)
_DAILY_ROUTES: tuple[str, ...] = (COVERAGE_ROUTE, *VENUE_ROUTES)
_DAILY_OUTCOMES: tuple[str, ...] = ("no_data",)


def load_answered_windows(conn: Any, symbol: str, timeframe: str, vendor: str) -> AnsweredWindows:
    """The answered TRADES windows `vendor` holds for (symbol, timeframe) (todo 462, 527).

    Intraday: a `bars` or `no_data` SMART answer (the bars corroborated by a raw row of the
    same vendor in the window, and not refused by the contract). 1d: a definitive `no_data` window on any route the vendor
    asks. Another source's requests never appear: the filter is the request's own source.
    """
    daily = timeframe == "1d"
    with conn.cursor() as cur:
        cur.execute(_MATCH_S_SQL, (MATCH_S_KEY,))
        found = cur.fetchall()
        if not found:
            raise RuntimeError(f"{MATCH_S_KEY} missing from config_state")
        cur.execute(
            _ANSWERED_WINDOWS_SQL,
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "vendor": vendor,
                "what": COVERAGE_WHAT_TO_SHOW,
                "routes": list(_DAILY_ROUTES if daily else _INTRADAY_ROUTES),
                "outcomes": list(_DAILY_OUTCOMES if daily else ANSWERED_OUTCOMES),
                "match_s": float(found[0][0]),
            },
        )
        rows = cur.fetchall()
    # A bar the answer served incomplete (migration 479, finding 5) is not an answer for its
    # slot: the window covers every other slot, never that one, until a later answer whose window
    # holds the slot serves it without listing it as partial (third review of 191-07, low item:
    # a slot once partial was otherwise re-asked forever).
    return AnsweredWindows.from_rows(
        [(_aware(r[0]), _aware(r[1])) for r in rows], partial=live_partials(rows)
    )


def live_partials(rows: Sequence[tuple]) -> set[datetime]:
    """Slots some answer served partial and no later answer covering them served whole.
    `rows` are (window_start, window_end, partial_bars, answered_at)."""
    marked: dict[datetime, datetime | None] = {}
    for r in rows:
        answered = _aware(r[3]) if len(r) > 3 and r[3] is not None else None
        for bar in _partial_list(r[2]):
            ts = _aware(datetime.fromisoformat(bar["t"]))
            prior = marked.get(ts)
            if ts not in marked or (answered is not None and (prior is None or answered > prior)):
                marked[ts] = answered
    live: set[datetime] = set()
    for ts, at in marked.items():
        cleared = at is not None and any(
            len(r) > 3
            and r[3] is not None
            and _aware(r[3]) > at
            and _aware(r[0]) <= ts < _aware(r[1])
            and ts not in {_aware(datetime.fromisoformat(b["t"])) for b in _partial_list(r[2])}
            for r in rows
        )
        if not cleared:
            live.add(ts)
    return live


def _partial_list(value: Any) -> list[dict[str, Any]]:
    """ohlcv_request.partial_bars as a list (psycopg returns jsonb decoded; a str is parsed)."""
    if value is None:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


def detect_gaps_from_record(
    conn: Any,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    expected_slots: Sequence[datetime],
    *,
    vendor: str,
    empty: EmptyRange | None = None,
    now: datetime | None = None,
    reverify_days: int | None = None,
    min_confirmations: int | None = None,
    on_skip: Callable[[EmptyRange], None] | None = None,
) -> list[tuple[datetime, datetime]]:
    """The gap plan for (symbol, timeframe) over [start_dt, end_dt] for `vendor`'s own raw.

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
        cur.execute(_RAW_SLOTS_SQL, (symbol, timeframe, vendor, start_dt, end_dt))
        rows = cur.fetchall()
    stored = [_aware(r[0]) for r in rows]
    answered = load_answered_windows(conn, symbol, timeframe, vendor)

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


# 1d: a session is covered by a complete bar of this vendor's own TRADES answer on its date (any
# kind: for IBKR smart_trades or a venue_<route> listing-venue route, D-20), or by a definitive
# no_data window containing the whole session day. The dividend-adjusted series answers a
# different question and covers nothing. Tradier's rows and requests belong to Tradier: IBKR is
# asked for every session it has not itself answered (owner, 2026-10-12, todo 533). Raw kinds
# are the per-route codes of vendor_kind, never the bare `venue` of the canonical tier.
_1D_STORED_SQL = """
SELECT "timestamp", served_at FROM ohlcv_raw
WHERE symbol = %s AND timeframe = '1d' AND vendor = %s AND kind <> ALL(%s)
  AND "timestamp" >= %s AND "timestamp" < %s
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
    vendor: str,
    empty: EmptyRange | None = None,
    now: datetime | None = None,
    reverify_days: int | None = None,
    min_confirmations: int | None = None,
    on_skip: Callable[[EmptyRange], None] | None = None,
) -> list[tuple[date, date]]:
    """The 1d gap plan for `symbol` over [start, end], from `vendor`'s own raw.

    `sessions` is the NYSE session map (src.intelligence.bars.sessions.
    nyse_sessions) over the window; a session date the vendor holds no complete bar for
    and no covering no_data window is a gap. One rule for every timeframe: plan_gaps with
    a one-day interval over session-midnight slots. Windows come back as contiguous
    end-exclusive (date, date) ranges -- the range ends at the last missing session's own
    day end, so the ask covers that whole day.

    A stored bar counts only when its session was complete when the vendor served it
    (session_complete_at(bar_date, served_at), D-191-J): a bar served while its session
    was still forming is not the vendor's answer for the day and stays a gap until a run
    sees the session whole. `now` caps the horizon exactly as the intraday readers cap
    theirs: only sessions closed by `now` are planned, so an unfinished current session is never
    asked and a closed one is asked from the moment it closes, not at the next 00:00 UTC.
    Without `now` the horizon is the whole requested window. The empty-history gate mirrors
    detect_gaps_from_record.
    """
    if end < start:
        return []
    with conn.cursor() as cur:
        cur.execute(
            _1D_STORED_SQL,
            (
                symbol,
                vendor,
                list(DAILY_NOT_COVERAGE_KINDS),
                midnight_utc(start),
                midnight_utc(end) + _1D_INTERVAL,
            ),
        )
        stored_rows = cur.fetchall()
    answered = load_answered_windows(conn, symbol, "1d", vendor)

    # A row without a serve time predates the serve stamp and counts (nothing to judge it by).
    stored = sorted(
        {
            _aware(stamp)
            for stamp, served_at in stored_rows
            if served_at is None
            or session_complete_at(_aware(stamp).date(), _aware(served_at), sessions)
        }
    )
    # Only a session that has closed is plannable: asking a forming session returns a partial
    # bar that never counts, and capping its window at `now` would collapse to a zero-length
    # (D, D) ask. A 1d window is never capped at now; it ends at the last planned session's own
    # day end, so the ask covers that whole day once the day is complete.
    slots = [
        midnight_utc(day)
        for day in sorted(sessions)
        if start <= day <= end and (now is None or session_complete_at(day, now, sessions))
    ]
    run_end = midnight_utc(end) + _1D_INTERVAL

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
    the planner's own end-exclusive (first session, day after the last session) shape, so the
    last session itself is covered; windows that touch or overlap merge into one request.
    `sessions` must hold only sessions closed at the run's time (a forming session is never
    re-asked). `overlap_sessions` of 0 returns the plan unchanged.
    """
    planned = list(gaps)
    if overlap_sessions <= 0:
        return planned
    eligible = sorted(day for day in sessions if day <= end)
    if not eligible:
        return planned
    windows = sorted([*planned, (eligible[-overlap_sessions:][0], eligible[-1] + _1D_INTERVAL)])
    merged: list[tuple[date, date]] = [windows[0]]
    for window_start, window_end in windows[1:]:
        prev_start, prev_end = merged[-1]
        if window_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, window_end))
        else:
            merged.append((window_start, window_end))
    return merged
