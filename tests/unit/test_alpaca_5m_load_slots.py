"""Slot-grid and first-writer-stays rules of the Alpaca 5m campaign loader (todo 521).

Pure logic only: no database, no parquet. The pins under test are the
admission-build plan's: bar-OPEN stamps, 78 slots on a 16:00 close, 42 on a
13:00 early close (from the calendar, not a constant), extended-hours bars
dropped at load, and a stored stamp never rewritten.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.ops.bars.ops_alpaca_5m_load import (
    drop_stored,
    filter_to_grid,
    rows_from_parquet,
    session_grid,
)

_ET = "America/New_York"


def _stamp(hour: int, minute: int, day: int = 6) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC).astimezone(
        __import__("zoneinfo").ZoneInfo(_ET)
    )


def _sessions() -> dict:
    """One full day (Tue 2026-10-06, 16:00 close) and one early close day
    (2026-10-02, 13:00 close), as nyse_sessions would return them."""
    open_full = _stamp(9, 30, day=6)
    return {
        open_full.date(): (open_full, _stamp(16, 0, day=6)),
        _stamp(9, 30, day=2).date(): (_stamp(9, 30, day=2), _stamp(13, 0, day=2)),
    }


def test_full_day_grid_is_78_open_stamps() -> None:
    grid = session_grid(_sessions(), {_stamp(9, 30, day=6).date()})
    stamps = grid[_stamp(9, 30, day=6).date()]
    assert len(stamps) == 78
    assert min(stamps) == _stamp(9, 30, day=6)
    assert max(stamps) == _stamp(15, 55, day=6)


def test_early_close_grid_is_42_open_stamps() -> None:
    grid = session_grid(_sessions(), {_stamp(9, 30, day=2).date()})
    stamps = grid[_stamp(9, 30, day=2).date()]
    assert len(stamps) == 42
    assert max(stamps) == _stamp(12, 55, day=2)


def test_grid_drops_weekend_and_off_grid_dates() -> None:
    saturday = _stamp(9, 30, day=3).date()
    grid = session_grid(_sessions(), {saturday})
    assert grid == {}


def test_filter_drops_extended_and_keeps_grid_slots() -> None:
    day = _stamp(9, 30, day=6).date()
    grid = session_grid(_sessions(), {day})

    def row(hour: int, minute: int) -> tuple:
        return (_stamp(hour, minute, day=6), "AMD", "5m", 1.0, 1.0, 1.0, 1.0, 10, "alpaca")

    rows = [row(4, 0), row(9, 30), row(12, 0), row(15, 55), row(16, 0), row(20, 0)]
    kept, dropped = filter_to_grid(rows, grid)
    assert dropped == 3
    assert [r[0] for r in kept] == [
        _stamp(9, 30, day=6),
        _stamp(12, 0, day=6),
        _stamp(15, 55, day=6),
    ]


def test_first_writer_stays_drops_stored_stamps() -> None:
    day = _stamp(9, 30, day=6).date()
    grid = session_grid(_sessions(), {day})

    def row(hour: int, minute: int) -> tuple:
        return (_stamp(hour, minute, day=6), "AMD", "5m", 1.0, 1.0, 1.0, 1.0, 10, "alpaca")

    rows = [row(9, 30), row(9, 35), row(9, 40)]
    stored = {_stamp(9, 30, day=6), _stamp(9, 40, day=6)}
    kept, skipped = drop_stored(rows, stored)
    assert skipped == 2
    assert [r[0] for r in kept] == [_stamp(9, 35, day=6)]


def test_rows_from_parquet_layout(tmp_path: Path) -> None:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "t": ["2026-10-06T13:30:00Z", "2026-10-06T19:55:00Z"],
            "o": [1.0, 2.0],
            "h": [1.5, 2.5],
            "l": [0.5, 1.5],
            "c": [1.2, 2.2],
            "v": [10, 20],
            "n": [1, 2],
            "vw": [1.1, 2.1],
        }
    )
    path = tmp_path / "AMD_5Min.parquet"
    frame.to_parquet(path, index=False)
    rows = rows_from_parquet(path, "AMD")
    assert len(rows) == 2
    ts, symbol, timeframe, o, h, low, c, v, source = rows[0]
    assert (symbol, timeframe, source) == ("AMD", "5m", "alpaca")
    assert (o, h, low, c, v) == (1.0, 1.5, 0.5, 1.2, 10)
    assert ts == datetime(2026, 10, 6, 13, 30, tzinfo=UTC)
    assert rows[1][0] == datetime(2026, 10, 6, 19, 55, tzinfo=UTC)


def test_five_minute_not_derivation_owned() -> None:
    from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES

    assert "5m" not in DERIVATION_OWNED_TIMEFRAMES
