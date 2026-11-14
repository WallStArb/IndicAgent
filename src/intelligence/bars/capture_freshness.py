"""How far a vendor's captured bars trail the last completed NYSE session.

Pure functions over a timestamp and the NYSE calendar; no database, no metrics. The nightly
capture reads the newest raw bar of a (vendor, timeframe), asks `sessions_behind`, and publishes
the count (todo 614 row 21). A 1d bar is stamped at the ET midnight of its session and a 5m bar
inside its session (extended hours stay on that date), so the ET date of a stamp is its session.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.intelligence.bars.sessions import nyse_sessions, session_complete_at

_NEW_YORK = ZoneInfo("America/New_York")
# Calendar window the completed sessions are listed from: it spans any NYSE closure run, so a
# stale latest stamp reports "at least this many behind", never a falsely small count.
_CALENDAR_WINDOW = timedelta(days=21)


def session_date_of(stamp: datetime) -> date:
    """The NYSE session date a UTC-aware bar stamp belongs to."""
    return stamp.astimezone(_NEW_YORK).date()


def completed_sessions(now: datetime) -> list[date]:
    """NYSE session dates whose close is at or before `now` (UTC-aware), ascending."""
    sessions = nyse_sessions(now.date() - _CALENDAR_WINDOW, now.date())
    return sorted(day for day in sessions if session_complete_at(day, now, sessions))


def sessions_behind(latest: datetime | None, now: datetime) -> int | None:
    """Completed sessions after the newest captured bar; None when nothing is captured.

    0 means the capture reaches the last completed session. Missing is None, never 0.
    """
    if latest is None:
        return None
    captured = session_date_of(latest)
    return sum(1 for day in completed_sessions(now) if day > captured)
