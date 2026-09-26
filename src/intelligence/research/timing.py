"""The book test's tested series (methodology-change-ledger E17, amending E16 (b), (c)).

For each tested session s, the book's timing P&L:

    D_s = sum_{rows r of s in trade} sum_j w[r, j] * (fwd[r, j] - fbar_L[s, pos(r), j])

w is the book's final weight (after construction and scaling; 0 where the row carries no
position), fwd its forward return (a missing return contributes 0, as in the construction),
and fbar_L[s, pos, j] the mean of the finite forward returns at bar position `pos` of symbol j
over the scored sessions with index below s - L. L is the signal's memory in sessions, read from
the spec (a member's slot_history_sessions; a book's largest over its members), so under H0 the
weight, built from the last L sessions, and fbar_L share no inputs (a weight on a session's last
bar, placed for the next session's first slot, reads sessions up to its own, still above s - L): D_s has zero mean even when every
(bar-of-session, symbol) cell has its own static mean return, which fbar_L removes. A cell
contributes only once fbar_L rests on at least `min_history_sessions` finite returns; without
that floor a name that lists late carries its static mean straight into w * fwd.

E16 subtracted causal expanding means of both w and fwd over every earlier session. For a
signal built from its own cell's recent returns, that fbar contains the returns that built w,
and the product had a nonzero mean under H0 (a mean-40-session member: H0 t about -2.6; the
book: H0 sd up to 1.6 and no power at IC 0.002; todo 432). E17 keeps the static-tilt removal
through fbar_L and drops the weight demean, which a static mean no longer needs.

The tested sessions are the scored ones with at least `warmup_sessions` scored sessions before
them and at least `min_history_sessions` scored sessions below s - L. hac.hac_mean_test on D
decides.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from src.intelligence.research.evaluate import SESSIONS_PER_YEAR
from src.intelligence.statistics.hac import HacTestResult, hac_mean_test

# E17's history floor: part of the statistic's definition, pinned by the methodology ledger
# (APR-exempt; changing it is a methodology change, not a tuning).
MIN_HISTORY_SESSIONS = 60


def timing_series(
    weights: np.ndarray,
    fwd: np.ndarray,
    has_position: np.ndarray,
    trade: np.ndarray,
    *,
    bars_per_session: int,
    warmup_sessions: int,
    memory_sessions: int,
    min_history_sessions: int = MIN_HISTORY_SESSIONS,
) -> np.ndarray:
    """[n_sessions] D_s, NaN on sessions that are not tested."""
    if memory_sessions < 1 or min_history_sessions < 1:
        raise ValueError(
            f"memory_sessions and min_history_sessions must be positive, got "
            f"{memory_sessions} and {min_history_sessions}"
        )
    n, m = weights.shape
    s_n = n // bars_per_session
    lag = memory_sessions
    shape = (s_n, bars_per_session, m)
    in_trade = trade.reshape(s_n, bars_per_session)[:, :, None]
    w = np.where(has_position[:, None], weights, 0.0).reshape(shape)
    finite = np.isfinite(fwd).reshape(shape) & in_trade
    r = np.where(finite, np.nan_to_num(fwd).reshape(shape), 0.0)
    scored = in_trade.any(axis=(1, 2))

    def below(values: np.ndarray) -> np.ndarray:
        """Sum over scored sessions with index below s - lag, for each session s."""
        total = np.cumsum(np.where(scored.reshape(-1, *[1] * (values.ndim - 1)), values, 0), axis=0)
        out = np.zeros(total.shape)
        out[lag + 1 :] = total[: s_n - lag - 1]
        return out

    prior_sessions = np.concatenate([[0], np.cumsum(scored)[:-1]])
    tested = (
        scored
        & (prior_sessions >= max(warmup_sessions, 1))
        & (below(scored.astype(np.float64)) >= min_history_sessions)
    )
    rows = np.flatnonzero(tested)
    out = np.full(s_n, np.nan)
    if rows.size == 0:
        return out
    count = below(finite.astype(np.float64))[rows]
    with np.errstate(invalid="ignore", divide="ignore"):
        fbar = np.where(count > 0, below(r)[rows] / count, 0.0)
    live = finite[rows] & (count >= min_history_sessions)
    out[rows] = (w[rows] * np.where(live, r[rows] - fbar, 0.0)).sum(axis=(1, 2))
    return out


@dataclasses.dataclass(frozen=True)
class TimingResult:
    hac: HacTestResult
    annualized_sharpe: float  # of the tested series, 252 sessions a year
    warmup_sessions: int
    memory_sessions: int  # L: fbar_L reads sessions older than the signal's memory
    min_history_sessions: int


def timing_test(
    weights: np.ndarray,
    fwd: np.ndarray,
    has_position: np.ndarray,
    trade: np.ndarray,
    *,
    bars_per_session: int,
    warmup_sessions: int,
    memory_sessions: int,
    min_history_sessions: int = MIN_HISTORY_SESSIONS,
) -> TimingResult:
    series = timing_series(
        weights,
        fwd,
        has_position,
        trade,
        bars_per_session=bars_per_session,
        warmup_sessions=warmup_sessions,
        memory_sessions=memory_sessions,
        min_history_sessions=min_history_sessions,
    )
    hac = hac_mean_test(series)
    x = series[np.isfinite(series)]
    sd = float(np.std(x, ddof=1))
    sharpe = float(np.mean(x)) / sd * math.sqrt(SESSIONS_PER_YEAR) if sd > 0 else float("nan")
    return TimingResult(
        hac=hac,
        annualized_sharpe=sharpe,
        warmup_sessions=warmup_sessions,
        memory_sessions=memory_sessions,
        min_history_sessions=min_history_sessions,
    )
