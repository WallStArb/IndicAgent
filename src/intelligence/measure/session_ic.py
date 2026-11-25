"""Per-session cross-sectional rank IC: the attempt series of an IC sweep cell (E21 rule 2).

A cell's series is its pooled per-session IC over the vintage: for every session, the Spearman
rank correlation across names of one feature with the target, on the names where both are finite
(the E21 "finite values only"). Pure arrays in and out; no database, no clock. The pooled
`ic.pooled_rank_ic` (strided, bootstrapped) stays the `feature_ic_scores` summary and is not
changed by this module.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata


def _rank_correlation(rank_x: np.ndarray, rank_y: np.ndarray) -> np.ndarray:
    """Pearson correlation of rank columns `rank_x` [k, F] with `rank_y` [k]; NaN where either
    side has no spread (a constant column has no rank correlation)."""
    x = rank_x - rank_x.mean(axis=0)
    y = rank_y - rank_y.mean()
    denominator = np.sqrt((x * x).sum(axis=0) * (y * y).sum())
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = (x * y[:, None]).sum(axis=0) / denominator
    return np.where(denominator > 0, corr, np.nan)


def session_rank_ic(
    features: np.ndarray,
    target: np.ndarray,
    exists: np.ndarray,
    *,
    min_names: int,
) -> np.ndarray:
    """Spearman IC per (session, feature): `features` [n, m, F], `target` [n, m], `exists`
    [n, m] bool (the slot is an observation: traded and carrying a feature row). Returns
    [n, F], NaN where fewer than `min_names` names are finite for the pair or a side is constant.
    Ties get average ranks. A feature finite on every name of the session shares one ranking of
    the target; a feature with holes is ranked on its own finite names."""
    if features.ndim != 3 or target.shape != features.shape[:2] or exists.shape != target.shape:
        raise ValueError(
            f"features {features.shape}, target {target.shape} and exists {exists.shape} "
            "must be [n, m, F], [n, m] and [n, m]"
        )
    if min_names < 3:
        raise ValueError(f"min_names must be >= 3, got {min_names}")
    n, _m, n_features = features.shape
    ic = np.full((n, n_features), np.nan)
    for i in range(n):
        names = exists[i] & np.isfinite(target[i])
        if int(names.sum()) < min_names:
            continue
        x = features[i][names]  # [k, F]
        y = target[i][names]
        finite = np.isfinite(x)
        whole = finite.all(axis=0)
        if whole.any():
            ic[i, whole] = _rank_correlation(rankdata(x[:, whole], axis=0), rankdata(y))
        holey = np.flatnonzero(~whole & (finite.sum(axis=0) >= min_names))
        if holey.size:
            # Features with the same finite names share one ranking of the target.
            patterns, group = np.unique(finite[:, holey], axis=1, return_inverse=True)
            for g in range(patterns.shape[1]):
                cols = holey[np.ravel(group) == g]
                keep = patterns[:, g]
                ic[i, cols] = _rank_correlation(
                    rankdata(x[keep][:, cols], axis=0), rankdata(y[keep])
                )
    return ic
