"""Session bounds sit on the 5m wall-clock grid the vendors stamp bars on.

The mcal NYSE schedule records a 09:32 open on 2006-12-27. Vendors stamp that day's bars on the
09:30 grid (QQQ has 78 five-minute bars, volume in the 09:30 bar), so a session anchored at the
raw open expected slots at :32, :37, ... that no bar can match: 78 phantom missing slots per name
in the intraday audit, and 15m/1h bars derived two minutes off the vendor grid.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.intelligence.bars.sessions import nyse_sessions

_FIVE_MINUTES = 5


def test_delayed_open_is_floored_to_the_five_minute_grid():
    day = date(2006, 12, 27)
    open_dt, close_dt = nyse_sessions(day, day)[day]
    assert open_dt == datetime(2006, 12, 27, 14, 30, tzinfo=UTC)
    assert close_dt == datetime(2006, 12, 27, 21, 0, tzinfo=UTC)


def test_every_open_since_2005_is_on_the_five_minute_grid():
    sessions = nyse_sessions(date(2005, 1, 1), date(2026, 10, 29))
    off_grid = [d for d, (o, _c) in sessions.items() if o.minute % _FIVE_MINUTES or o.second]
    assert off_grid == []


def test_ordinary_sessions_are_unchanged():
    day = date(2026, 10, 29)
    open_dt, close_dt = nyse_sessions(day, day)[day]
    assert open_dt == datetime(2026, 10, 29, 13, 30, tzinfo=UTC)
    assert close_dt == datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
