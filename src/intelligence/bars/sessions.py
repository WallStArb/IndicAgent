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

from datetime import UTC, date, datetime
from functools import lru_cache

import pandas_market_calendars as mcal


@lru_cache(maxsize=32)
def nyse_sessions(start: date, end: date) -> dict[date, tuple[datetime, datetime]]:
    """Per-trading-date NYSE session bounds as UTC-aware datetimes.

    Covers every session from start through end inclusive: keys are trading
    dates, values are (market_open, market_close) with early closes (13:00 ET)
    on half days and DST-correct 09:30 ET opens. Non-trading days are absent.
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
        sessions[day] = (open_dt, close_dt)
    return sessions
