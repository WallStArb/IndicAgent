"""Family 2: overnight versus intraday return decomposition (docs/plans/2026-09-25-family2-
overnight-intraday-prereg.md; Lou, Polk and Skouras 2019; Berkman et al. 2012).

Members read the session-legs panel's S1 residual returns (`legs.py`): row 0 of a session is its
overnight leg, rows 1 and 2 its intraday leg. Every member places alpha for session d on row 1
of d, formed at bar 0's close, and the target is the rest of the session.

| Member | statistic for session d | window_sessions | Sign |
|---|---|---|---|
| O1/O2 intraday_persistence | mean residual intraday return over d-w .. d-1 | 20 / 60 | +1 |
| O3/O4 overnight_to_intraday | mean residual overnight return over d-w .. d-1 | 20 / 60 | -1 |
| O5 gap_fade | residual overnight return of d | - | -1 |
| O6 gap_fade_z | O5 over the sample sd of d-w .. d-1 overnight residuals | 60 | -1 |

Signs are the members' definitions (prereg section 3), applied before the centred rank; the
book's construction direction is +1. Means and the sd need at least half the window's sessions
finite (the sd also at least 2 and a positive value). The alpha row must itself have a finite
residual.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.families.common import centred_rank
from src.intelligence.research.legs import LEGS, SIGNAL_LEG


def _legs(resid: np.ndarray, bars_per_session: int) -> np.ndarray:
    if bars_per_session != LEGS:
        raise ValueError(f"family 2 members need the {LEGS}-row legs panel, got {bars_per_session}")
    n, m = resid.shape
    return resid.reshape(n // LEGS, LEGS, m)


def _prior_window(x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Over sessions d-window .. d-1 of x [S, m]: (count finite, sum, sum of squares), each
    [S, m], from prefix sums (index d covers sessions < d)."""
    finite = np.isfinite(x)
    zeros = np.zeros((1, x.shape[1]))
    xs = np.where(finite, x, 0.0)
    prefix = [np.concatenate([zeros, np.cumsum(a, axis=0)]) for a in (finite, xs, xs * xs)]
    lo = np.maximum(np.arange(len(x)) - window, 0)
    hi = np.arange(len(x))
    return tuple(p[hi] - p[lo] for p in prefix)


def _prior_mean(x: np.ndarray, window: int) -> np.ndarray:
    count, total, _ = _prior_window(x, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count >= (window + 1) // 2, total / count, np.nan)


def _place(stat: np.ndarray, resid: np.ndarray, coverage_floor: int) -> np.ndarray:
    """stat [S, m] onto row 1 of each session, NaN where row 1's residual is missing, ranked."""
    alpha = np.full(resid.shape, np.nan)
    alpha[SIGNAL_LEG::LEGS] = stat
    alpha[~np.isfinite(resid)] = np.nan
    return centred_rank(alpha, coverage_floor=coverage_floor)


def intraday_persistence(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O1/O2: +mean residual intraday return (rows 1 + 2) over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    intraday = legs[:, 1] + legs[:, 2]  # NaN if either leg is missing
    return _place(_prior_mean(intraday, window_sessions), resid_bar_returns, coverage_floor)


def overnight_to_intraday(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O3/O4: -mean residual overnight return (row 0) over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    return _place(-_prior_mean(legs[:, 0], window_sessions), resid_bar_returns, coverage_floor)


def gap_fade(
    resid_bar_returns: np.ndarray, *, bars_per_session: int, coverage_floor: int
) -> np.ndarray:
    """O5: -residual overnight return of the same session (row 0 of d)."""
    legs = _legs(resid_bar_returns, bars_per_session)
    return _place(-legs[:, 0], resid_bar_returns, coverage_floor)


def gap_fade_z(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O6: -(row 0 of d) over the sample sd of row 0 over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    gap = legs[:, 0]
    count, total, sq = _prior_window(gap, window_sessions)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (sq - total * total / count) / (count - 1)
        sd = np.sqrt(np.where(var > 0, var, np.nan))
        ok = (count >= max((window_sessions + 1) // 2, 2)) & np.isfinite(sd)
        stat = np.where(ok, -gap / sd, np.nan)
    return _place(stat, resid_bar_returns, coverage_floor)
