"""The E16 book test's tested series (methodology-change-ledger E16, pinned (b), (c), with the
adoption refinement on returns).

For each scored session s after the warmup, the book's timing P&L:

    D_s = sum_{rows r of s in trade} sum_j (w[r, j] - wbar[s - 1, pos(r), j])
                                          * (fwd[r, j] - fbar[s - 1, pos(r), j])

w is the book's final weight (after construction and scaling; 0 where the row carries no
position), fwd its forward return (a missing return contributes 0, as in the construction),
and wbar[s - 1, pos, j] the mean of w at bar position `pos` of the session over all scored
sessions before s, a session without weight counting as 0, not renormalized. The tilt is per
(bar-of-session, symbol): the shift null this replaces kept each bar's time of day, so the
static exposure it held fixed was per slot; on a daily panel (one bar per session) it is the
pinned per-symbol tilt. A book that always holds the same weights has D identically 0: it is
not timing anything.

fbar is the same causal expanding mean of the forward return (over finite returns only). The
pinned form used fwd itself; subtracting fbar leaves the expectation unchanged (the covariance
of weight deviations with return deviations) and removes the term (w - wbar) * mean return,
which is as persistent as the predictor. With static slot or name means in residual returns
that term made the pinned form oversized under H0 (0.135 at the 0.00167 bar, tau 200), while
this form held size (scripts/analysis/e16_null_size/slot_tilt_size.py, recorded in E16).

The tested sessions are the scored ones with at least `warmup_sessions` scored sessions before
them, so both means are defined. hac.hac_mean_test on D decides.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from src.intelligence.research.evaluate import SESSIONS_PER_YEAR
from src.intelligence.statistics.hac import HacTestResult, hac_mean_test


def timing_series(
    weights: np.ndarray,
    fwd: np.ndarray,
    has_position: np.ndarray,
    trade: np.ndarray,
    *,
    bars_per_session: int,
    warmup_sessions: int,
) -> np.ndarray:
    """[n_sessions] D_s, NaN on sessions that are not tested."""
    n, m = weights.shape
    s_n = n // bars_per_session
    shape = (s_n, bars_per_session, m)
    in_trade = trade.reshape(s_n, bars_per_session)[:, :, None]
    w = np.where(has_position[:, None], weights, 0.0).reshape(shape)
    finite = np.isfinite(fwd).reshape(shape) & in_trade
    r = np.where(finite, np.nan_to_num(fwd).reshape(shape), 0.0)
    scored = in_trade.any(axis=(1, 2))

    def prior(values: np.ndarray) -> np.ndarray:
        """Sum over scored sessions strictly before each session."""
        total = np.cumsum(np.where(scored[:, None, None], values, 0.0), axis=0)
        return np.concatenate([np.zeros((1, *values.shape[1:])), total[:-1]])

    prior_sessions = np.concatenate([[0], np.cumsum(scored)[:-1]])
    tested = scored & (prior_sessions >= max(warmup_sessions, 1))
    rows = np.flatnonzero(tested)
    out = np.full(s_n, np.nan)
    if rows.size == 0:
        return out
    wbar = prior(w)[rows] / prior_sessions[rows, None, None]
    r_count = prior(finite.astype(np.float64))[rows]
    with np.errstate(invalid="ignore", divide="ignore"):
        fbar = np.where(r_count > 0, prior(r)[rows] / r_count, 0.0)
    deviation = np.where(finite[rows], r[rows] - fbar, 0.0)
    out[rows] = ((w[rows] - wbar) * deviation).sum(axis=(1, 2))
    return out


@dataclasses.dataclass(frozen=True)
class TimingResult:
    hac: HacTestResult
    annualized_sharpe: float  # of the tested series, 252 sessions a year
    warmup_sessions: int


def timing_test(
    weights: np.ndarray,
    fwd: np.ndarray,
    has_position: np.ndarray,
    trade: np.ndarray,
    *,
    bars_per_session: int,
    warmup_sessions: int,
) -> TimingResult:
    series = timing_series(
        weights,
        fwd,
        has_position,
        trade,
        bars_per_session=bars_per_session,
        warmup_sessions=warmup_sessions,
    )
    hac = hac_mean_test(series)
    x = series[np.isfinite(series)]
    sd = float(np.std(x, ddof=1))
    sharpe = float(np.mean(x)) / sd * math.sqrt(SESSIONS_PER_YEAR) if sd > 0 else float("nan")
    return TimingResult(hac=hac, annualized_sharpe=sharpe, warmup_sessions=warmup_sessions)
