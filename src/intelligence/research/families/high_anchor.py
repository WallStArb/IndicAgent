"""52-week-high anchoring (docs/plans/2026-11-15-family9-52week-high-prereg-draft.md, ledger E26;
George and Hwang 2004).

One member, F1 `high_distance_252`: for row d, (c[d] - max(c[d-251..d])) / max(c[d-251..d]) over
the total-return close c, at most 0 and 0 on a new high. Sign +1: nearer the high ranks higher.
The target enters at d+1's open, so the member reads nothing inside the target window.

No fill: a window reaching before the first row of the panel is not a window (NaN), a window with
fewer than `min_finite` finite closes is NaN (a missing session can hide the high), and so is a
row whose own close is missing (the name did not trade on d) or whose maximum is not positive.

The member reads closes, not S1 residual returns, so it needs a close input the member contract
does not have yet (families/common.py: members read residual returns). Until that input kind
lands this module is a tested pure kernel with no `NULL_BATTERY`, so `runner.static_gate` refuses
the family before the ledger.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.families.common import centred_rank


def high_distance(close: np.ndarray, *, window: int, min_finite: int) -> np.ndarray:
    """[S, m] (c - rolling max) / rolling max over the `window` sessions ending at each row,
    NaN where the rules in the module docstring apply. The window is folded in
    one lag at a time, never materialised as a [S, m, window] array (about 3.4 times the input
    in peak memory, measured at 5,000 x 1,000)."""
    if not 1 <= min_finite <= window:
        raise ValueError(f"need 1 <= min_finite <= window, got {min_finite} and {window}")
    c = np.asarray(close, dtype=float)
    if c.ndim != 2:
        raise ValueError(f"close must be [sessions, names], got shape {c.shape}")
    finite = np.isfinite(c)
    high = np.full(c.shape, np.nan)
    count = np.zeros(c.shape, dtype=np.int16)
    for lag in range(min(window, len(c))):
        np.fmax(high[lag:], c[: len(c) - lag], out=high[lag:])
        count[lag:] += finite[: len(c) - lag]
    with np.errstate(invalid="ignore", divide="ignore"):
        distance = c / high - 1.0
    ok = (count >= min_finite) & (high > 0)
    ok[: window - 1] = False
    return np.where(ok, distance, np.nan)


def high_distance_member(
    close: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window: int,
    min_finite: int,
) -> np.ndarray:
    """F1: +high_distance, centred-ranked per row (the member contract of families/common.py)."""
    if bars_per_session != 1:
        raise ValueError(f"high-anchor members need the 1d panel, got {bars_per_session}")
    return centred_rank(
        high_distance(close, window=window, min_finite=min_finite), coverage_floor=coverage_floor
    )
