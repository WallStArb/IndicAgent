"""Whole-panel circular-shift null and Westfall-Young max-statistic adjustment.

Phase 179 pre-registration section 7 (docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md).
The null shifts an entire date x symbol panel by k sessions, every symbol by the same k, so
each date's cross-section moves intact: cross-asset correlation and signal persistence survive,
only the alignment with future returns is broken. The shifts are enumerated exhaustively over
min_shift <= k <= n - min_shift, so the null is deterministic (no RNG).

Missing values are NaN cells that shift with their row, so the panel must be dense on a shared
date axis; a ragged per-symbol event panel breaks synchrony (todo 372).

Pure functions only -- no DB, no config loading.
"""

from __future__ import annotations

import numpy as np


def admissible_shifts(n: int, min_shift: int, memory: int = 0) -> np.ndarray:
    """Every shift k with min_shift <= k <= n - min_shift - memory, ascending.

    The lower bound keeps a slow feature's autocorrelation from leaking the true alignment
    back into the null; the upper bound is the same distance from a full rotation, which
    is the true alignment again. `memory` is how many sessions after the signal date the
    target can reach back into the signal's own window (the signal's lookback plus the
    return's span): a copy wrapped from within that distance after a date would read that
    date's target return, so those shifts are excluded.
    """
    if min_shift < 1:
        raise ValueError(
            f"min_shift must be >= 1 (k = 0 is the observed alignment), got {min_shift}"
        )
    if memory < 0:
        raise ValueError(f"memory must be >= 0, got {memory}")
    if n - min_shift - memory < min_shift:
        raise ValueError(
            f"no admissible shift: n={n} is shorter than 2 * min_shift + memory="
            f"{2 * min_shift + memory}"
        )
    return np.arange(min_shift, n - min_shift - memory + 1)


def shift_panel(panel: np.ndarray, k: int) -> np.ndarray:
    """Circularly shift a date x symbol panel along the date axis: out[t] = panel[(t - k) mod n].

    Returns a new array; the input is not modified.
    """
    if panel.ndim != 2:
        raise ValueError(f"panel must be 2-D (date x symbol), got shape {panel.shape}")
    n = panel.shape[0]
    if not 0 < k < n:
        raise ValueError(f"shift k must satisfy 0 < k < n={n}, got {k}")
    return np.roll(panel, k, axis=0)


def westfall_young_adjusted_p(observed: np.ndarray, null: np.ndarray) -> np.ndarray:
    """One-sided Westfall-Young max-statistic adjusted p-values across arms.

    observed: shape (J,), one statistic per arm on the real panel.
    null: shape (K, J), the same statistics on each of K shifted panels, shared across arms
    so the rows carry the arms' exact joint null.

    Each arm is standardized by its own null (mean, population sd), M_k = max_j Z_j(k), and
    p_j = (1 + #{k: M_k >= Z_j_obs}) / (1 + K). Controls family-wise error strongly and,
    unlike Holm, does not pay for correlated arms. Raises rather than returning a p-value
    when any input is non-finite or an arm's null has zero variance.
    """
    observed = np.asarray(observed, dtype=float)
    null = np.asarray(null, dtype=float)
    if observed.ndim != 1 or null.ndim != 2 or null.shape[1] != observed.shape[0]:
        raise ValueError(
            f"shape mismatch: observed {observed.shape}, null {null.shape}; need (J,) and (K, J)"
        )
    if not np.isfinite(observed).all() or not np.isfinite(null).all():
        raise ValueError("non-finite value in observed or null statistics")
    # A constant column can have a float-rounded sd of ~1e-17, not 0, so test the range.
    zero_var = np.ptp(null, axis=0) == 0
    if zero_var.any():
        raise ValueError(f"arm null has zero variance: arms {np.flatnonzero(zero_var).tolist()}")
    mean = null.mean(axis=0)
    sd = null.std(axis=0)
    z_obs = (observed - mean) / sd
    max_null = ((null - mean) / sd).max(axis=1)
    exceed = (max_null[:, None] >= z_obs[None, :]).sum(axis=0)
    return (1 + exceed) / (1 + null.shape[0])
