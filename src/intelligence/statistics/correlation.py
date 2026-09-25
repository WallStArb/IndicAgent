"""Pairwise-complete correlation of a [T, m] panel with missing values.

Pure function, no DB, no config. Shared by S1's clustering and PC estimation
(src/intelligence/research/factors.py) and the residual-breadth diagnostic.
"""

from __future__ import annotations

import numpy as np


def pairwise_corr(x: np.ndarray, min_overlap: int = 0) -> np.ndarray:
    """[m, m] Pearson correlation of each pair of columns over the rows where both are finite,
    after demeaning each column over its own finite rows. A pair observed together on fewer
    than min_overlap rows, or with zero variance on its overlap, gets 0; the diagonal is 1.
    Complete data takes a fast path with the same arithmetic (one fewer product)."""
    mask = np.isfinite(x)
    x0 = np.where(mask, x - np.nanmean(x, axis=0), 0.0)
    cross = x0.T @ x0
    if mask.all():
        ss = np.diag(cross)
        denom = np.sqrt(np.outer(ss, ss))
        overlap = np.full(cross.shape, x.shape[0])
    else:
        m = mask.astype(float)
        sq = (x0**2).T @ m  # [i, j]: sum of x_i^2 over rows where j is also observed
        denom = np.sqrt(sq * sq.T)
        overlap = m.T @ m
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.where(denom > 0, cross / denom, 0.0)
    corr[overlap < min_overlap] = 0.0
    np.fill_diagonal(corr, 1.0)
    return corr
