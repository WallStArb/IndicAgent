"""B1b: each grid row's availability time (multi-timeframe design D4, D7 guard 3).

A grid row's availability time is the earlier of its slot end and its session close, from the
NYSE calendar; NaT where no symbol traded; nothing is filled. A 1d row is available at its
session's calendar close.

Every cross-clock read (align.py) compares two of these arrays, so a wrong close is a silent
lookahead. Two shortcuts are wrong and are not used here: a fixed 16:00 ET close (late on a
13:00 ET half day) and slot start plus tf length (on the short 15:30-16:00 1h bucket it says
16:30, and on a half day the 12:30 bucket would say 13:30). The calendar (mcal through
bars/sessions.nyse_sessions) carries early closes and both DST transitions.

A traded row whose slot start lies outside its calendar session (a vendor bar after an early
close, a date the calendar has no session for) is refused, never given a close past the
session close.
"""

from __future__ import annotations

from datetime import UTC, date

import numpy as np
import pandas as pd

from src.intelligence.bars.sessions import nyse_sessions

# Schema identifiers for the intraday timeframes and their slot lengths, not tunables.
TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
DAILY_TF = "1d"
# Exchange time zone the grid's session dates are keyed in (snapshot.build_grid).
_EXCHANGE_TZ = "America/New_York"


def closes_at(
    timestamps: np.ndarray, valid: np.ndarray, tf: str, bars_per_session: int
) -> np.ndarray:
    """datetime64[ns] [n] naive UTC: each row's availability time, NaT where `valid` is False.

    `timestamps` are a Panel's: datetime64[D] session dates on 1d, naive UTC slot starts
    intraday. Raises ValueError on an unknown tf, a shape mismatch, or a traded row outside
    its calendar session.
    """
    ts = np.asarray(timestamps)
    valid = np.asarray(valid, dtype=bool)
    n = len(ts)
    if valid.shape != (n,):
        raise ValueError(f"closes_at (B1b): valid has shape {valid.shape}, expected {(n,)}")
    if bars_per_session < 1 or n % bars_per_session:
        raise ValueError(
            f"closes_at (B1b): {n} rows is not a whole number of {bars_per_session}-bar sessions"
        )
    if tf == DAILY_TF:
        starts = None
        days = ts.astype("datetime64[D]")
    elif tf in TF_MINUTES:
        starts = ts.astype("datetime64[ns]")
        local = pd.DatetimeIndex(starts).tz_localize(UTC).tz_convert(_EXCHANGE_TZ)
        days = local.normalize().tz_localize(None).values.astype("datetime64[D]")
    else:
        raise ValueError(f"closes_at (B1b): unknown tf {tf!r}")

    out = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    rows = np.flatnonzero(valid)
    if len(rows) == 0:
        return out
    cal_days, cal_opens, cal_closes = _calendar(days[rows].min(), days[rows].max())
    pos = np.searchsorted(cal_days, days[rows])
    found = pos < len(cal_days)
    found[found] = cal_days[pos[found]] == days[rows][found]
    if not found.all():
        i = int(rows[np.flatnonzero(~found)[0]])
        raise ValueError(
            f"closes_at (B1b): row {i} is dated {days[i]}, which is not an NYSE session"
        )
    close = cal_closes[pos]
    if starts is None:
        out[rows] = close
        return out
    slot = starts[rows]
    outside = (slot < cal_opens[pos]) | (slot >= close)
    if outside.any():
        i = int(rows[np.flatnonzero(outside)[0]])
        raise ValueError(
            f"closes_at (B1b): row {i} starts at {starts[i]} outside the {days[i]} session"
        )
    out[rows] = np.minimum(slot + np.timedelta64(TF_MINUTES[tf], "m"), close)
    return out


def _calendar(
    first: np.datetime64, last: np.datetime64
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sorted session dates (datetime64[D]) with their opens and closes (datetime64[ns] naive
    UTC) from one nyse_sessions call over [first, last]."""
    sessions = nyse_sessions(_as_date(first), _as_date(last))
    keys = sorted(sessions)
    days = np.array(keys, dtype="datetime64[D]")
    opens = np.array([_naive_utc(sessions[d][0]) for d in keys], dtype="datetime64[ns]")
    closes = np.array([_naive_utc(sessions[d][1]) for d in keys], dtype="datetime64[ns]")
    return days, opens, closes


def _as_date(day: np.datetime64) -> date:
    return day.astype("datetime64[D]").astype(object)


def _naive_utc(dt) -> np.datetime64:
    return np.datetime64(dt.astimezone(UTC).replace(tzinfo=None), "ns")
