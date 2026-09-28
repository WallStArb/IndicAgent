"""Session-anchored aggregation of 5m bars onto the 15m/1h grid (D2b, D-15).

Buckets anchor at the session open (09:30 ET), never at midnight-UTC floors:
bucket k spans [session_open + k*minutes, session_open + (k+1)*minutes) and no
bucket crosses the session close. The last bucket of a session may be short
(15:30-16:00 on full days, 12:30-13:00 on half days) and holds only constituents
that lie before the close, which the half-open [open, close) validity mask
guarantees structurally. This replaces aggregate_bars_from_1m's midnight-UTC
flooring (the :00-edge bug D-15 exists to remove); its per-bucket formulas
(first open, max high, min low, last close, summed volume) are the ones kept.

Pure: session bounds arrive as an injected Mapping so no calendar module is
imported here (src/core/market_calendar.py is an ic_engine import and stays
untouched). Bars outside every session window (or on non-session days) are
dropped and counted, never silently aggregated. minutes is a statistic
definition (15 or 60), passed by the caller, not an APR value.

first_index/last_index point into the input arrays (including any dropped
outside-session rows), so callers can union constituent 5m quarantine flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GridBars:
    """Aggregated bars on session-anchored edges, in ascending stamp order.

    ts_seconds are int64 bucket-start UTC epoch seconds; open/high/low/close and
    volume are float64; n_constituents is int32; first_index/last_index are the
    int64 input positions of the bucket's first and last constituent bar;
    n_outside_session counts input bars that fell outside every session window.
    """

    ts_seconds: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    n_constituents: np.ndarray
    first_index: np.ndarray
    last_index: np.ndarray
    n_outside_session: int


def _empty_grid(n_outside_session: int) -> GridBars:
    return GridBars(
        ts_seconds=np.empty(0, dtype=np.int64),
        open=np.empty(0, dtype=np.float64),
        high=np.empty(0, dtype=np.float64),
        low=np.empty(0, dtype=np.float64),
        close=np.empty(0, dtype=np.float64),
        volume=np.empty(0, dtype=np.float64),
        n_constituents=np.empty(0, dtype=np.int32),
        first_index=np.empty(0, dtype=np.int64),
        last_index=np.empty(0, dtype=np.int64),
        n_outside_session=n_outside_session,
    )


def aggregate_session_grid(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    sessions: Mapping[date, tuple[datetime, datetime]],
    minutes: int,
) -> GridBars:
    """Aggregate 5m bars (stamped at bar start, sorted ascending) into `minutes` buckets.

    A bar belongs to the session keyed by its America/New_York calendar date;
    bars whose date has no session, or whose stamp falls outside the session's
    [open, close) window, are dropped and counted in n_outside_session. Buckets
    with no input produce no row. Raises ValueError on unsorted stamps, on
    mismatched array lengths, or on a non-positive minutes.
    """
    ts_seconds = np.asarray(ts_seconds, dtype=np.int64)
    open_ = np.asarray(open_, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)
    volume = np.asarray(volume, dtype=np.float64)
    n = ts_seconds.size
    if n == 0:
        return _empty_grid(0)
    if minutes <= 0:
        raise ValueError(f"minutes must be positive, got {minutes}")
    lengths = {array.size for array in (open_, high, low, close, volume)}
    if lengths != {n}:
        raise ValueError(f"array lengths disagree: ts {n}, ohlcv {sorted(lengths)}")
    if n > 1 and int(np.diff(ts_seconds).min()) < 0:
        raise ValueError("ts_seconds must be sorted ascending")

    # Session lookup: ET calendar date per bar, mapped through the injected
    # sessions. Unique dates only (hundreds per range), then vectorized inverse.
    et_index = pd.to_datetime(ts_seconds, unit="s", utc=True).tz_convert(_ET)
    date_code = (
        et_index.year.to_numpy().astype(np.int64) * 10_000
        + et_index.month.to_numpy().astype(np.int64) * 100
        + et_index.day.to_numpy().astype(np.int64)
    )
    unique_codes, inverse = np.unique(date_code, return_inverse=True)
    open_by_code = np.full(unique_codes.size, -1, dtype=np.int64)
    close_by_code = np.full(unique_codes.size, -1, dtype=np.int64)
    for j, code in enumerate(unique_codes):
        session = sessions.get(date(int(code // 10_000), int(code // 100) % 100, int(code % 100)))
        if session is not None:
            open_by_code[j] = int(session[0].timestamp())
            close_by_code[j] = int(session[1].timestamp())

    bar_open = open_by_code[inverse]
    bar_close = close_by_code[inverse]
    valid = (bar_open >= 0) & (ts_seconds >= bar_open) & (ts_seconds < bar_close)
    n_outside_session = int(n - np.count_nonzero(valid))
    keep = np.flatnonzero(valid)
    if keep.size == 0:
        return _empty_grid(n_outside_session)

    # Bucket stamps are nondecreasing on sorted input: sessions are day-separated
    # and every stamp lies inside its own session, so buckets form contiguous runs.
    session_open = bar_open[keep]
    stamp = session_open + (ts_seconds[keep] - session_open) // (minutes * 60) * (minutes * 60)
    starts = np.flatnonzero(np.r_[True, stamp[1:] != stamp[:-1]])
    ends = np.r_[starts[1:], keep.size] - 1

    kept_open = open_[keep]
    kept_close = close[keep]
    return GridBars(
        ts_seconds=stamp[starts],
        open=kept_open[starts],
        high=np.maximum.reduceat(high[keep], starts),
        low=np.minimum.reduceat(low[keep], starts),
        close=kept_close[ends],
        volume=np.add.reduceat(volume[keep], starts),
        n_constituents=(ends - starts + 1).astype(np.int32),
        first_index=keep[starts],
        last_index=keep[ends],
        n_outside_session=n_outside_session,
    )
