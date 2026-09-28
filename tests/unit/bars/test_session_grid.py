"""Session-anchored grid aggregation tests (D2b, D-15).

Derived 15m/1h bars must equal an independent direct computation from 5m, sit on
session-anchored edges (09:30, 09:45, ... and 09:30, 10:30, ... ET), never span
a session, drop outside-session inputs with a count, and hold on the 2025-11-28
half day and both 2025 DST-transition days, for synthetic sessions and the
committed SPY fixtures.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from src.intelligence.bars.session_grid import GridBars, aggregate_session_grid
from src.intelligence.bars.sessions import nyse_sessions
from tests.unit.bars._builders import fake_session, five_minute_bars

_ET = ZoneInfo("America/New_York")
_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bars"
_EPOCH = pd.Timestamp("1970-01-01", tz=UTC)

# (date string, open ET, close ET): a full day, the 2025-11-28 half day, and both
# 2025 DST-transition days as synthetic sessions.
_SESSION_CASES = [
    ("2026-06-02", "09:30", "16:00"),
    ("2025-11-28", "09:30", "13:00"),
    ("2025-03-10", "09:30", "16:00"),
    ("2025-11-03", "09:30", "16:00"),
]


def _seconds(stamps: pd.DatetimeIndex | pd.Series) -> np.ndarray:
    """UTC timestamps as int64 epoch seconds, unit-resolution agnostic."""
    delta = pd.DatetimeIndex(stamps) - _EPOCH
    return np.asarray(delta // pd.Timedelta(seconds=1), dtype=np.int64)


def _from_builder(bars: dict) -> dict[str, np.ndarray]:
    return {
        "ts_seconds": _seconds(bars["timestamp"]),
        "open": np.asarray(bars["open"], dtype=np.float64),
        "high": np.asarray(bars["high"], dtype=np.float64),
        "low": np.asarray(bars["low"], dtype=np.float64),
        "close": np.asarray(bars["close"], dtype=np.float64),
        "volume": np.asarray(bars["volume"], dtype=np.float64),
    }


def _load_5m_fixture(name: str) -> dict[str, np.ndarray]:
    df = pd.read_csv(_FIXTURE_DIR / name)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return {
        "ts_seconds": np.asarray((ts - _EPOCH) // pd.Timedelta(seconds=1), dtype=np.int64),
        "open": df["open"].to_numpy(dtype=np.float64),
        "high": df["high"].to_numpy(dtype=np.float64),
        "low": df["low"].to_numpy(dtype=np.float64),
        "close": df["close"].to_numpy(dtype=np.float64),
        "volume": df["volume"].to_numpy(dtype=np.float64),
    }


def _args(bars: dict[str, np.ndarray], sessions: dict, minutes: int) -> dict:
    return {
        "ts_seconds": bars["ts_seconds"],
        "open_": bars["open"],
        "high": bars["high"],
        "low": bars["low"],
        "close": bars["close"],
        "volume": bars["volume"],
        "sessions": sessions,
        "minutes": minutes,
    }


def _et_date(ts: int) -> date:
    return datetime.fromtimestamp(ts, tz=UTC).astimezone(_ET).date()


def _et_wall_clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).astimezone(_ET).strftime("%H:%M")


def _direct_grid(
    bars: dict[str, np.ndarray], sessions: dict, minutes: int
) -> tuple[list[dict], int]:
    """Independent Python-loop aggregation of the same inputs (no numpy reduceat)."""
    grouped: dict[tuple[date, int], list[int]] = {}
    n_outside = 0
    for i in range(bars["ts_seconds"].size):
        ts = int(bars["ts_seconds"][i])
        session = sessions.get(_et_date(ts))
        if session is None:
            n_outside += 1
            continue
        open_s = int(session[0].timestamp())
        close_s = int(session[1].timestamp())
        if not open_s <= ts < close_s:
            n_outside += 1
            continue
        k = (ts - open_s) // (minutes * 60)
        grouped.setdefault((_et_date(ts), k), []).append(i)
    rows = []
    for day, k in sorted(grouped):
        idxs = grouped[(day, k)]
        rows.append(
            {
                "ts": int(sessions[day][0].timestamp()) + k * minutes * 60,
                "open": float(bars["open"][idxs[0]]),
                "high": max(float(bars["high"][j]) for j in idxs),
                "low": min(float(bars["low"][j]) for j in idxs),
                "close": float(bars["close"][idxs[-1]]),
                "volume": float(sum(float(bars["volume"][j]) for j in idxs)),
                "n": len(idxs),
                "first": idxs[0],
                "last": idxs[-1],
            }
        )
    return rows, n_outside


def _assert_matches_direct(
    grid: GridBars, bars: dict[str, np.ndarray], sessions: dict, minutes: int
) -> None:
    rows, n_outside = _direct_grid(bars, sessions, minutes)
    assert grid.n_outside_session == n_outside
    assert grid.ts_seconds.size == len(rows)
    for j, row in enumerate(rows):
        assert int(grid.ts_seconds[j]) == row["ts"]
        assert grid.open[j] == row["open"]
        assert grid.high[j] == row["high"]
        assert grid.low[j] == row["low"]
        assert grid.close[j] == row["close"]
        assert grid.volume[j] == row["volume"]
        assert int(grid.n_constituents[j]) == row["n"]
        assert int(grid.first_index[j]) == row["first"]
        assert int(grid.last_index[j]) == row["last"]


# ---------------------------------------------------------------------------
# nyse_sessions
# ---------------------------------------------------------------------------


def test_nyse_sessions_half_day_and_thanksgiving_absent() -> None:
    sessions = nyse_sessions(date(2025, 11, 24), date(2025, 11, 28))
    assert sorted(sessions) == [
        date(2025, 11, 24),
        date(2025, 11, 25),
        date(2025, 11, 26),
        date(2025, 11, 28),
    ]
    # Half day: 2025-11-28 closes 13:00 ET (18:00 UTC).
    open_dt, close_dt = sessions[date(2025, 11, 28)]
    assert open_dt == datetime(2025, 11, 28, 14, 30, tzinfo=UTC)
    assert close_dt == datetime(2025, 11, 28, 18, 0, tzinfo=UTC)
    # Full day closes 16:00 ET (21:00 UTC).
    open_dt, close_dt = sessions[date(2025, 11, 24)]
    assert (open_dt, close_dt) == (
        datetime(2025, 11, 24, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 24, 21, 0, tzinfo=UTC),
    )


def test_nyse_sessions_dst_transition_opens() -> None:
    sessions = nyse_sessions(date(2025, 3, 10), date(2025, 11, 3))
    # 09:30 ET is 13:30 UTC after spring-forward, 14:30 UTC after fall-back.
    assert sessions[date(2025, 3, 10)][0] == datetime(2025, 3, 10, 13, 30, tzinfo=UTC)
    assert sessions[date(2025, 11, 3)][0] == datetime(2025, 11, 3, 14, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# aggregate_session_grid: shapes and edges
# ---------------------------------------------------------------------------


def test_full_day_grid_shapes() -> None:
    day = date(2026, 6, 2)
    sessions = {day: fake_session("2026-06-02", "09:30", "16:00")}
    bars = _from_builder(five_minute_bars(*sessions[day], seed=11))
    assert bars["ts_seconds"].size == 78

    grid15 = aggregate_session_grid(**_args(bars, sessions, 15))
    assert grid15.ts_seconds.size == 26
    stamps15 = [_et_wall_clock(int(t)) for t in grid15.ts_seconds]
    assert stamps15[0] == "09:30"
    assert stamps15[-1] == "15:45"

    grid60 = aggregate_session_grid(**_args(bars, sessions, 60))
    assert grid60.ts_seconds.size == 7
    stamps60 = [_et_wall_clock(int(t)) for t in grid60.ts_seconds]
    assert stamps60 == ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    # The last 1h bucket is the short 15:30-16:00 span: 6 five-minute bars.
    assert int(grid60.n_constituents[-1]) == 6


def test_half_day_grid_shapes() -> None:
    day = date(2025, 11, 28)
    sessions = {day: fake_session("2025-11-28", "09:30", "13:00")}
    bars = _from_builder(five_minute_bars(*sessions[day], seed=5))
    assert bars["ts_seconds"].size == 42

    grid60 = aggregate_session_grid(**_args(bars, sessions, 60))
    assert grid60.ts_seconds.size == 4
    stamps60 = [_et_wall_clock(int(t)) for t in grid60.ts_seconds]
    assert stamps60 == ["09:30", "10:30", "11:30", "12:30"]
    # The short last bucket is 12:30-13:00: 6 five-minute bars.
    assert int(grid60.n_constituents[-1]) == 6

    grid15 = aggregate_session_grid(**_args(bars, sessions, 15))
    assert grid15.ts_seconds.size == 14
    assert grid15.volume.sum() == bars["volume"].sum()


@pytest.mark.parametrize("minutes", [15, 60])
@pytest.mark.parametrize(("date_str", "open_hhmm", "close_hhmm"), _SESSION_CASES)
@pytest.mark.parametrize("seed", [3, 17])
def test_grid_equals_direct_loop(
    date_str: str, open_hhmm: str, close_hhmm: str, seed: int, minutes: int
) -> None:
    day = date.fromisoformat(date_str)
    sessions = {day: fake_session(date_str, open_hhmm, close_hhmm)}
    bars = _from_builder(five_minute_bars(*sessions[day], seed=seed))
    grid = aggregate_session_grid(**_args(bars, sessions, minutes))
    _assert_matches_direct(grid, bars, sessions, minutes)


def test_two_consecutive_sessions_never_mix() -> None:
    day1, day2 = date(2026, 6, 1), date(2026, 6, 2)
    sessions = {
        day1: fake_session("2026-06-01", "09:30", "16:00"),
        day2: fake_session("2026-06-02", "09:30", "16:00"),
    }
    first = _from_builder(five_minute_bars(*sessions[day1], seed=1))
    second = _from_builder(five_minute_bars(*sessions[day2], seed=2))
    bars = {key: np.concatenate([first[key], second[key]]) for key in first}

    grid = aggregate_session_grid(**_args(bars, sessions, 60))
    assert grid.ts_seconds.size == 14
    assert Counter(_et_date(int(t)) for t in grid.ts_seconds) == {day1: 7, day2: 7}

    for j in range(grid.ts_seconds.size):
        stamp = int(grid.ts_seconds[j])
        session_day = _et_date(stamp)
        open_s = int(sessions[session_day][0].timestamp())
        close_s = int(sessions[session_day][1].timestamp())
        assert open_s <= stamp < close_s
        # No bucket holds bars from two sessions: every constituent lies inside
        # this bucket's own session window.
        constituents = bars["ts_seconds"][grid.first_index[j] : grid.last_index[j] + 1]
        assert constituents.size == int(grid.n_constituents[j])
        assert (constituents >= open_s).all()
        assert (constituents < close_s).all()
        last_of_session = (
            j + 1 >= grid.ts_seconds.size or _et_date(int(grid.ts_seconds[j + 1])) != session_day
        )
        if not last_of_session:
            # Only the short last bucket of a session may end past the close.
            assert stamp + 3600 <= close_s


def test_outside_session_bars_dropped_and_counted() -> None:
    day = date(2026, 6, 2)
    sessions = {day: fake_session("2026-06-02", "09:30", "16:00")}
    clean = _from_builder(five_minute_bars(*sessions[day], seed=9))

    # Wall-clock times whose stamps fall outside [09:30, 16:00) ET on the session
    # day, or on a non-session calendar day (Sunday). The 20:00 ET stamp lands on
    # the next UTC day, exercising the ET-date mapping.
    outside = [
        ("2026-06-02", "08:55"),
        ("2026-06-02", "09:29"),
        ("2026-06-02", "16:00"),
        ("2026-06-02", "20:00"),
        ("2026-06-07", "11:00"),
    ]
    extra_ts = np.array(
        [int(fake_session(d, hm, hm)[0].timestamp()) for d, hm in outside], dtype=np.int64
    )
    extra = {
        "ts_seconds": extra_ts,
        "open": np.full(extra_ts.size, 500.0),
        "high": np.full(extra_ts.size, 501.0),
        "low": np.full(extra_ts.size, 499.0),
        "close": np.full(extra_ts.size, 500.5),
        "volume": np.full(extra_ts.size, 7.0),
    }
    merged = {key: np.concatenate([clean[key], extra[key]]) for key in clean}
    order = np.argsort(merged["ts_seconds"], kind="stable")
    merged = {key: merged[key][order] for key in merged}

    grid = aggregate_session_grid(**_args(merged, sessions, 60))
    assert grid.n_outside_session == len(outside)
    _assert_matches_direct(grid, merged, sessions, 60)

    clean_grid = aggregate_session_grid(**_args(clean, sessions, 60))
    assert clean_grid.n_outside_session == 0
    assert np.array_equal(grid.ts_seconds, clean_grid.ts_seconds)
    assert np.array_equal(grid.open, clean_grid.open)
    assert np.array_equal(grid.high, clean_grid.high)
    assert np.array_equal(grid.low, clean_grid.low)
    assert np.array_equal(grid.close, clean_grid.close)
    assert np.array_equal(grid.volume, clean_grid.volume)


def test_empty_input_returns_empty_grid() -> None:
    grid = aggregate_session_grid(
        np.empty(0, dtype=np.int64),
        np.empty(0, dtype=np.float64),
        np.empty(0, dtype=np.float64),
        np.empty(0, dtype=np.float64),
        np.empty(0, dtype=np.float64),
        np.empty(0, dtype=np.float64),
        {},
        15,
    )
    assert grid.ts_seconds.size == 0
    assert grid.n_outside_session == 0


def test_unsorted_input_raises() -> None:
    day = date(2026, 6, 2)
    sessions = {day: fake_session("2026-06-02", "09:30", "16:00")}
    bars = _from_builder(five_minute_bars(*sessions[day], seed=4))
    reversed_bars = {key: bars[key][::-1].copy() for key in bars}
    with pytest.raises(ValueError, match="sorted ascending"):
        aggregate_session_grid(**_args(reversed_bars, sessions, 15))


# ---------------------------------------------------------------------------
# SPY fixtures
# ---------------------------------------------------------------------------


def test_spy_half_day_fixture() -> None:
    bars = _load_5m_fixture("spy_5m_2025_11_28_half_day.csv")
    day = date(2025, 11, 28)
    sessions = nyse_sessions(day, day)
    assert bars["ts_seconds"].size == 42

    for minutes in (15, 60):
        grid = aggregate_session_grid(**_args(bars, sessions, minutes))
        _assert_matches_direct(grid, bars, sessions, minutes)

    grid60 = aggregate_session_grid(**_args(bars, sessions, 60))
    assert grid60.ts_seconds.size == 4
    assert _et_wall_clock(int(grid60.ts_seconds[-1])) == "12:30"
    assert int(grid60.n_constituents[-1]) == 6
    grid15 = aggregate_session_grid(**_args(bars, sessions, 15))
    assert grid15.ts_seconds.size == 14
    assert grid60.volume.sum() == bars["volume"].sum()
    assert grid15.volume.sum() == bars["volume"].sum()


def test_spy_dst_fixture_both_days() -> None:
    bars = _load_5m_fixture("spy_5m_dst_2025_03_10_2025_11_03.csv")
    days = [date(2025, 3, 10), date(2025, 11, 3)]
    sessions = nyse_sessions(days[0], days[1])
    assert bars["ts_seconds"].size == 156

    for minutes in (15, 60):
        grid = aggregate_session_grid(**_args(bars, sessions, minutes))
        _assert_matches_direct(grid, bars, sessions, minutes)
        for day in days:
            grid_day = np.array([_et_date(int(t)) == day for t in grid.ts_seconds])
            bars_day = np.array([_et_date(int(t)) == day for t in bars["ts_seconds"]])
            assert grid.volume[grid_day].sum() == bars["volume"][bars_day].sum()

    grid60 = aggregate_session_grid(**_args(bars, sessions, 60))
    assert Counter(_et_date(int(t)) for t in grid60.ts_seconds) == {days[0]: 7, days[1]: 7}
    stamps = {
        day: [_et_wall_clock(int(t)) for t in grid60.ts_seconds if _et_date(int(t)) == day]
        for day in days
    }
    assert stamps[days[0]] == ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
    assert stamps[days[1]] == ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
