"""Same-calendar-month return seasonality (docs/plans/2026-11-15-published-prior-top3-prereg-
drafts.md H-C; Heston and Sadka 2008; Keloharju, Linnainmaa and Nyberg 2016).

Members read monthly sums of the daily panel's S1 residual returns. For row d the label month m is
the calendar month of session d+1, the session the target enters in; only months before m are
read, and every month before m is complete at d's close (when d is the last session of its month
that month is m-1). The last row has no d+1 and is NaN.

| Member | statistic for label month m | months read | Sign |
|---|---|---|---|
| H-C1 seasonal_same_month | mean of the monthly sums at m-12k, k = 1..lags | lags | +1 |
| H-C2 seasonal_other_months | mean of the monthly sums over m-1..m-window, same calendar month as m excluded | window | -1 |

A monthly sum is masked (NaN, never filled) when the share of its sessions with a missing residual
exceeds `max_missing_fraction`; the first month of the panel is always masked (its start may be
mid-month, so its session count is unknown). H-C1 needs at least `min_lags` finite lags and H-C2
at least half of its months finite. The sign is the member's definition, applied before the
centred rank.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.families.common import needs_session_dates
from src.intelligence.research.families.daily_residual import _daily, _place

# The longest session count in a calendar month; bounds how many sessions a read of N months can
# reach back (declared memory = slot history + S1's reach, common.declared_memory_rows).
MAX_SESSIONS_PER_MONTH = 23


def slot_history_sessions(months: int) -> int:
    """An upper bound, in sessions, of the history a read of `months` months before the label
    month can need: the label month's own sessions plus `months` whole months."""
    return (months + 1) * MAX_SESSIONS_PER_MONTH


def _month_index(session_dates: np.ndarray) -> np.ndarray:
    d = np.asarray(session_dates).astype("datetime64[M]")
    return d.astype(int)  # months since 1970-01, ascending with the sessions


def _monthly_sums(e: np.ndarray, month: np.ndarray, max_missing_fraction: float) -> np.ndarray:
    """[n_months, m] sum of e over each calendar month's sessions, NaN for a masked month. The
    months are the contiguous range first..last of `month`; a month the panel lacks is NaN."""
    first = int(month[0])
    n_months = int(month[-1]) - first + 1
    pos = month - first
    finite = np.isfinite(e)
    sums = np.zeros((n_months, e.shape[1]))
    seen = np.zeros((n_months, e.shape[1]))
    np.add.at(sums, pos, np.where(finite, e, 0.0))
    np.add.at(seen, pos, finite.astype(float))
    sessions = np.bincount(pos, minlength=n_months).astype(float)[:, None]
    ok = (sessions > 0) & (seen >= (1.0 - max_missing_fraction) * sessions) & (seen > 0)
    ok[0] = False  # the panel's first month may be partial
    return np.where(ok, sums, np.nan)


def _label_positions(month: np.ndarray) -> np.ndarray:
    """int [n], each row's label month as an index into the monthly array (the month of session
    d+1), -1 for the last row, which has no next session."""
    pos = month - int(month[0])
    label = np.empty(len(month), dtype=np.int64)
    label[:-1] = pos[1:]
    label[-1] = -1
    return label


def _lag_mean(
    monthly: np.ndarray, label: np.ndarray, lags: np.ndarray, min_finite: int
) -> np.ndarray:
    """[n_months, m]: for each label month p the mean of monthly[p - lag] over `lags`, NaN with
    fewer than `min_finite` finite values (a lag before the panel start is missing)."""
    n_months, m = monthly.shape
    total = np.zeros((n_months, m))
    count = np.zeros((n_months, m))
    for lag in lags.tolist():
        if lag >= n_months:
            continue
        shifted = np.full((n_months, m), np.nan)
        shifted[lag:] = monthly[: n_months - lag]
        got = np.isfinite(shifted)
        total += np.where(got, shifted, 0.0)
        count += got
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count >= min_finite, total / count, np.nan)


def _seasonal(
    resid: np.ndarray,
    session_dates: np.ndarray,
    lags: np.ndarray,
    min_finite: int,
    max_missing_fraction: float,
    sign: int,
    coverage_floor: int,
) -> np.ndarray:
    if len(session_dates) != len(resid):
        raise ValueError(f"{len(session_dates)} session dates for {len(resid)} rows")
    month = _month_index(session_dates)
    monthly = _monthly_sums(resid, month, max_missing_fraction)
    by_month = sign * _lag_mean(monthly, month, lags, min_finite)
    label = _label_positions(month)
    stat = np.full(resid.shape, np.nan)
    has_label = label >= 0
    stat[has_label] = by_month[label[has_label]]
    return _place(stat, resid, coverage_floor)


@needs_session_dates
def seasonal_same_month(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    session_dates: np.ndarray,
    lags: int,
    min_lags: int,
    max_missing_fraction: float,
) -> np.ndarray:
    """H-C1: +mean of the monthly residual sums at m-12, m-24, .. m-12*lags (at least
    `min_lags` finite)."""
    if not 1 <= min_lags <= lags:
        raise ValueError(f"need 1 <= min_lags <= lags, got {min_lags} and {lags}")
    return _seasonal(
        _daily(resid_bar_returns, bars_per_session),
        session_dates,
        12 * np.arange(1, lags + 1),
        min_lags,
        max_missing_fraction,
        +1,
        coverage_floor,
    )


@needs_session_dates
def seasonal_other_months(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    session_dates: np.ndarray,
    window_months: int,
    max_missing_fraction: float,
) -> np.ndarray:
    """H-C2: -mean of the monthly residual sums over m-1 .. m-window_months, every month whose
    calendar month equals m's excluded; at least half of those months finite."""
    lags = np.array([k for k in range(1, window_months + 1) if k % 12], dtype=int)
    if not lags.size:
        raise ValueError(f"window_months {window_months} leaves no month to read")
    return _seasonal(
        _daily(resid_bar_returns, bars_per_session),
        session_dates,
        lags,
        (len(lags) + 1) // 2,
        max_missing_fraction,
        -1,
        coverage_floor,
    )
