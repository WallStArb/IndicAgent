"""NYSE session bounds for the derived grid (D2b, phase 185 plan 06).

src/core/market_calendar.py already builds per-date session bounds from
pandas_market_calendars, but ic_engine imports it and the live-run rule forbids
editing it; this module is the phase 185 helper plans 11+ read instead. Same
source of truth (the mcal NYSE schedule, which carries early closes and both
DST transitions), new module, nothing shared mutated.

The returned dict is shared through the lru cache: treat it as immutable and
pass it to aggregate_session_grid unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pandas_market_calendars as mcal

_GRID_SECONDS = 300  # the finest derived grid; vendors stamp bars on this wall-clock grid


def _floor_to_grid(stamp: datetime) -> datetime:
    """`stamp` floored to the 5m wall-clock grid (a no-op for every 09:30 open)."""
    return stamp - timedelta(seconds=stamp.timestamp() % _GRID_SECONDS)


@lru_cache(maxsize=32)
def nyse_sessions(start: date, end: date) -> dict[date, tuple[datetime, datetime]]:
    """Per-trading-date NYSE session bounds as UTC-aware datetimes.

    Covers every session from start through end inclusive: keys are trading
    dates, values are (market_open, market_close) with early closes (13:00 ET)
    on half days and DST-correct 09:30 ET opens. Non-trading days are absent. The open is floored
    to the 5m grid: mcal records a 09:32 open on 2006-12-27 while vendors stamp that day on the
    09:30 grid, and a session anchored off the grid expects slots no bar can occupy.
    Raises ValueError when end precedes start.
    """
    if end < start:
        raise ValueError(f"nyse_sessions: end {end} precedes start {start}")
    schedule = mcal.get_calendar("NYSE").schedule(start.isoformat(), end.isoformat())
    sessions: dict[date, tuple[datetime, datetime]] = {}
    for stamp, row in schedule.iterrows():
        day = stamp.date()
        open_dt = row["market_open"].to_pydatetime()
        close_dt = row["market_close"].to_pydatetime()
        if open_dt.tzinfo is None:
            open_dt = open_dt.replace(tzinfo=UTC)
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=UTC)
        sessions[day] = (_floor_to_grid(open_dt), close_dt)
    return sessions


def session_complete_at(
    day: date,
    at: datetime,
    sessions: Mapping[date, tuple[datetime, datetime]] | None = None,
) -> bool:
    """True when the NYSE session of `day` has closed at `at` (UTC-aware).

    `sessions` is an already-built nyse_sessions map covering `day`; a caller judging many days
    passes it instead of asking the calendar once per day.

    A 1d bar served before its session closes is still forming: it is not a complete vendor
    answer for the day (D-191-J). A date with no NYSE session is treated as complete, so a
    calendar gap never withholds a bar the vendor served for a past date.
    """
    session = (sessions if sessions is not None else nyse_sessions(day, day)).get(day)
    if session is None:
        return day < at.date()
    return at >= session[1]
