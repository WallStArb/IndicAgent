"""Slot-grid and first-writer-stays rules of the Alpaca 5m campaign loader (todo 521).

Pure logic only: no database. The pins under test are the admission-build
plan's: bar-OPEN stamps, 78 slots on a 16:00 close, 42 on a 13:00 early
close (from the calendar's session bounds, not a constant), extended-hours
bars dropped at load, and a stored stamp never rewritten.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from services.bar_load import (
    LoadPolicy,
    drop_stored_rows,
    filter_frame_to_grid,
    frame_to_tuples,
    grid_stamps_utc,
    session_grid,
)

_ET = ZoneInfo("America/New_York")
POLICY = LoadPolicy(vendor="alpaca", timeframe="5m", caller="test")
_FULL_DAY = datetime(2026, 10, 6, tzinfo=UTC).date()
_EARLY_DAY = datetime(2026, 10, 2, tzinfo=UTC).date()


def _stamp(hour: int, minute: int, day: int = 6) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=_ET)


def _sessions() -> dict:
    """One full day (2026-10-06, 16:00 close) and one early close (2026-10-02,
    13:00 close), the shape `nyse_sessions` returns."""
    return {
        _FULL_DAY: (_stamp(9, 30), _stamp(16, 0)),
        _EARLY_DAY: (_stamp(9, 30, day=2), _stamp(13, 0, day=2)),
    }


def _frame(hour_minutes: list[tuple[int, int]], day: int = 6) -> pd.DataFrame:
    stamps = [datetime(2026, 10, day, h, m, tzinfo=_ET) for h, m in hour_minutes]
    n = len(stamps)
    return pd.DataFrame(
        {
            "t": pd.to_datetime(stamps, utc=True),
            "o": [1.0] * n,
            "h": [1.0] * n,
            "l": [1.0] * n,
            "c": [1.0] * n,
            "v": [10] * n,
            "n": [1] * n,
            "vw": [1.0] * n,
        }
    )


def test_full_day_grid_is_78_open_stamps() -> None:
    grid = session_grid(_sessions(), {_FULL_DAY})
    stamps = grid[_FULL_DAY]
    assert len(stamps) == 78
    assert min(stamps) == _stamp(9, 30)
    assert max(stamps) == _stamp(15, 55)


def test_early_close_grid_is_42_open_stamps() -> None:
    grid = session_grid(_sessions(), {_EARLY_DAY})
    stamps = grid[_EARLY_DAY]
    assert len(stamps) == 42
    assert max(stamps) == _stamp(12, 55, day=2)


def test_grid_drops_non_session_dates() -> None:
    saturday = datetime(2026, 10, 3, tzinfo=UTC).date()
    assert session_grid(_sessions(), {saturday}) == {}


def test_grid_filter_drops_extended_and_keeps_grid_slots() -> None:
    grid = session_grid(_sessions(), {_FULL_DAY})
    utc_stamps = grid_stamps_utc(grid)
    frame = _frame([(4, 0), (9, 30), (12, 0), (15, 55), (16, 0), (20, 0)])
    kept = filter_frame_to_grid(frame, utc_stamps)
    assert len(kept) == 3
    assert list(kept["t"].dt.hour) == [13, 16, 19]  # UTC
    assert list(kept["t"].dt.minute) == [30, 0, 55]


def test_first_writer_stays_drops_stored_stamps() -> None:
    grid = session_grid(_sessions(), {_FULL_DAY})
    utc_stamps = grid_stamps_utc(grid)
    frame = _frame([(9, 30), (9, 35), (9, 40)])
    stored = {datetime(2026, 10, 6, 13, 30, tzinfo=UTC), datetime(2026, 10, 6, 13, 40, tzinfo=UTC)}
    kept = drop_stored_rows(filter_frame_to_grid(frame, utc_stamps), stored)
    assert len(kept) == 1
    assert kept["t"].iloc[0] == pd.Timestamp(2026, 10, 6, 13, 35, tz="UTC")  # 09:35 ET


def test_frame_to_tuples_layout() -> None:
    frame = _frame([(9, 30)])
    rows = frame_to_tuples(frame, "AMD", POLICY)
    assert len(rows) == 1
    ts, symbol, timeframe, o, h, low, c, v, source = rows[0]
    assert (symbol, timeframe, source) == ("AMD", "5m", "alpaca")
    assert (o, h, low, c, v) == (1.0, 1.0, 1.0, 1.0, 10)
    assert ts == datetime(2026, 10, 6, 13, 30, tzinfo=UTC)  # 09:30 ET


def test_five_minute_not_derivation_owned() -> None:
    from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES

    assert "5m" not in DERIVATION_OWNED_TIMEFRAMES


def test_utc_grid_matches_utc_frame_stamps() -> None:
    """The grid is ET-aware; the frame is UTC; the membership join must agree
    across the conversion (DST-safe by construction of astimezone)."""
    grid = session_grid(_sessions(), {_FULL_DAY})
    utc_stamps = grid_stamps_utc(grid)
    assert len(utc_stamps) == 78
    assert datetime(2026, 10, 6, 13, 30, tzinfo=UTC) in utc_stamps
    assert datetime(2026, 10, 6, 19, 55, tzinfo=UTC) in utc_stamps
