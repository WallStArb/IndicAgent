"""Daily residual momentum and short-term reversal (docs/plans/2026-10-27-daily-residual-
momentum-reversal-prereg.md; Blitz, Huij and Martens 2011; Jegadeesh 1990; Lehmann 1990; Da, Liu
and Schaumburg 2014).

Members read the daily panel's S1 residual returns e[s, i] (close to close, known at s's close)
over sessions up to and including the signal row d, and place alpha on row d; the target enters
at d+1's open.

| Member | statistic for row d | sessions | Sign |
|---|---|---|---|
| M1 residual_momentum | sum of e over d-251 .. d-21 | 231 | +1 |
| M2 residual_momentum_z | mean(e) / sd(e, ddof 1) over the same sessions | 231 | +1 |
| R1/R2 residual_reversal | sum of e over d-(w-1) .. d, w = 5 / 21 | w | -1 |
| R3 residual_reversal (skip 1) | sum of e over d-5 .. d-1 | 5 | -1 |

A window needs at least half its sessions finite (M2 also at least 2 and a positive sd), else
NaN. The alpha row must itself have a finite residual (the name traded on d). Signs are the
members' definitions, applied before the centred rank; the construction direction is +1.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.families.common import centred_rank

# The E17 H0 battery that gates this family (runner.static_gate); a name, since it imports us.
NULL_BATTERY = "src.intelligence.research.null_battery_daily_residual"

MOMENTUM_SESSIONS = 231  # prereg section 3: the 12-1 month formation window (APR-exempt)
MOMENTUM_SKIP_SESSIONS = 21  # the skipped most recent month


def _daily(resid: np.ndarray, bars_per_session: int) -> np.ndarray:
    if bars_per_session != 1:
        raise ValueError(f"daily residual members need the 1d panel, got {bars_per_session}")
    return resid


def _window(x: np.ndarray, length: int, skip: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Over sessions d-skip-length+1 .. d-skip of x [S, m]: (count finite, sum, sum of squares),
    each [S, m]. Each window is summed from its own sessions only, never as a difference of
    prefix sums, whose rounding carries every earlier session into the window (family 2's S3
    memory guard failure, a138749f7)."""
    finite = np.isfinite(x)
    xs = np.where(finite, x, 0.0)
    pad = np.zeros((length + skip, x.shape[1]))
    out = []
    for a in (finite.astype(float), xs, xs * xs):
        windows = np.lib.stride_tricks.sliding_window_view(np.concatenate([pad, a]), length, axis=0)
        out.append(windows[1 : len(x) + 1].sum(axis=-1))  # row d: padded d+1 .. d+length
    return tuple(out)


def _place(stat: np.ndarray, resid: np.ndarray, coverage_floor: int) -> np.ndarray:
    alpha = np.where(np.isfinite(resid), stat, np.nan)
    return centred_rank(alpha, coverage_floor=coverage_floor)


def _sum(resid: np.ndarray, length: int, skip: int) -> np.ndarray:
    count, total, _ = _window(resid, length, skip)
    return np.where(count >= (length + 1) // 2, total, np.nan)


def residual_momentum(
    resid_bar_returns: np.ndarray, *, bars_per_session: int, coverage_floor: int
) -> np.ndarray:
    """M1: +sum of residual returns over d-251 .. d-21."""
    e = _daily(resid_bar_returns, bars_per_session)
    stat = _sum(e, MOMENTUM_SESSIONS, MOMENTUM_SKIP_SESSIONS)
    return _place(stat, e, coverage_floor)


def residual_momentum_z(
    resid_bar_returns: np.ndarray, *, bars_per_session: int, coverage_floor: int
) -> np.ndarray:
    """M2: +mean over sd (ddof 1) of residual returns over d-251 .. d-21."""
    e = _daily(resid_bar_returns, bars_per_session)
    count, total, sq = _window(e, MOMENTUM_SESSIONS, MOMENTUM_SKIP_SESSIONS)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = total / count
        var = (sq - total * total / count) / (count - 1)
        sd = np.sqrt(np.where(var > 0, var, np.nan))
        ok = (count >= max((MOMENTUM_SESSIONS + 1) // 2, 2)) & np.isfinite(sd)
        stat = np.where(ok, mean / sd, np.nan)
    return _place(stat, e, coverage_floor)


def residual_reversal(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
    skip_sessions: int = 0,
) -> np.ndarray:
    """R1/R2/R3: -sum of residual returns over d-skip-window+1 .. d-skip."""
    e = _daily(resid_bar_returns, bars_per_session)
    return _place(-_sum(e, window_sessions, skip_sessions), e, coverage_floor)
