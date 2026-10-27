"""Synthetic multi-timeframe grids on real NYSE sessions (phase 184).

Shared by the clock, align and later 184 tests. Bars sit on the calendar's own slots: intraday
slot starts step from the 09:30 ET open by the tf length while they start before the session
close, so the last 1h bucket is the short 15:30-16:00 one and a half day stops at 13:00 ET.
The sessions cover a 13:00 ET half day (2024-11-29, after Thanksgiving) and both 2024 DST
transitions with their neighbours. Not a test module.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

import numpy as np

from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.research.panel import Panel
from src.intelligence.research.snapshot import build_grid, session_dates

HALF_DAY = date(2024, 11, 29)
BEFORE_HALF_DAY = date(2024, 11, 27)
DST_SPRING = date(2024, 3, 11)  # first EDT session
BEFORE_DST_SPRING = date(2024, 3, 8)  # last EST session
DST_FALL = date(2024, 11, 4)  # first EST session
BEFORE_DST_FALL = date(2024, 11, 1)  # last EDT session

ALL_SESSIONS = (
    BEFORE_DST_SPRING,
    DST_SPRING,
    BEFORE_DST_FALL,
    DST_FALL,
    BEFORE_HALF_DAY,
    HALF_DAY,
)
SYMBOLS = ("AAA", "BBB", "CCC")

_TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60}


def bars(times_utc: Sequence, closes: Sequence[float]):
    """One symbol's bars in the build_grid tuple shape: (ts ns UTC naive, open, close, volume)."""
    ts = np.array(times_utc, dtype="datetime64[ns]")
    c = np.asarray(closes, dtype=float)
    return ts, c - 0.5, c, np.full(len(c), 100.0)


def session_bounds(day: date) -> tuple[datetime, datetime]:
    """The calendar's (open, close) for `day`, UTC-aware."""
    return nyse_sessions(day, day)[day]


def slot_starts(day: date, tf: str) -> list[datetime]:
    """UTC naive slot starts of `day` on `tf`: from the open, every tf length, before the close."""
    open_dt, close_dt = session_bounds(day)
    step = timedelta(minutes=_TF_MINUTES[tf])
    out, t = [], open_dt
    while t < close_dt:
        out.append(t.astimezone(UTC).replace(tzinfo=None))
        t += step
    return out


def _walk(rng: np.random.Generator, n: int) -> np.ndarray:
    return 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))


def intraday_grid(
    tf: str,
    sessions: Iterable[date] = ALL_SESSIONS,
    symbols: Sequence[str] = SYMBOLS,
    seed: int = 0,
) -> Panel:
    """A build_grid panel on `tf` with every symbol trading every calendar slot of `sessions`."""
    times = [t for day in sorted(sessions) for t in slot_starts(day, tf)]
    rng = np.random.default_rng(seed)
    return build_grid({s: bars(times, _walk(rng, len(times))) for s in symbols}, tf)


def daily_grid(
    sessions: Iterable[date] = ALL_SESSIONS,
    symbols: Sequence[str] = SYMBOLS,
    seed: int = 0,
) -> Panel:
    """A 1d build_grid panel, one bar per session stamped at 00:00 UTC of the session date."""
    times = [datetime(d.year, d.month, d.day) for d in sorted(sessions)]
    rng = np.random.default_rng(seed)
    return build_grid({s: bars(times, _walk(rng, len(times))) for s in symbols}, "1d")


def drop_rows(panel: Panel, rows: Iterable[int]) -> Panel:
    """The panel with `rows` untraded by every symbol: valid False and NaN prices."""
    rows = np.asarray(list(rows), dtype=int)
    valid = panel.valid.copy()
    valid[rows] = False
    prices = {}
    for name in ("open", "close", "volume"):
        values = getattr(panel, name).copy()
        values[rows] = np.nan
        prices[name] = values
    return dataclasses.replace(panel, valid=valid, **prices)


def session_rows(panel: Panel, day: date) -> np.ndarray:
    """Row numbers of `day`'s session on an intraday panel (valid or not)."""
    k = int(np.flatnonzero(session_dates(panel) == np.datetime64(day, "D"))[0])
    return np.arange(k * panel.bars_per_session, (k + 1) * panel.bars_per_session)


def utc(text: str) -> np.datetime64:
    """A naive UTC instant as datetime64[ns]."""
    return np.datetime64(text, "ns")
