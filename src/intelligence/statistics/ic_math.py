"""Shared IC (Information Coefficient) math -- Fisher z-transform CI, vectorized Spearman
IC, HAC-corrected rolling Sharpe, and p-values.

Extracted from services/ic_engine.py (todo 048, 2026-07-02): services/ensemble_ic_engine.py
and scripts/ops/corpus/ops_oos_holdout_eval.py were each importing these same
underscore-prefixed "private" functions directly from ic_engine.py -- three Ring 2
consumers reaching into one module's internals instead of a shared public API. Moving the
math here (Ring 1, no domain-vocab restriction like Ring 0) gives all three a stable import
target; a change to ic_engine.py's internals can no longer silently break its siblings.

Pure functions only -- no DB, no config loading, no module-global mutable state (besides
the _Z95 constant). config.sharpe_window_size / config.sharpe_min_windows are accessed via
the SharpeWindowConfig protocol rather than importing ICEngineConfig or EnsembleICConfig,
so this module has no dependency back on either concrete config dataclass.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from scipy.stats import rankdata
from scipy.stats import t as t_dist

_Z95 = 1.959963985  # norm.ppf(0.975) — 95% two-tailed critical value


class SharpeWindowConfig(Protocol):
    """Duck-typed shape _compute_ic_rolling_metrics needs from a frozen IC config
    dataclass. Both ICEngineConfig and EnsembleICConfig satisfy this structurally."""

    sharpe_window_size: int
    sharpe_min_windows: int
    hac_max_lag: int


# ---------------------------------------------------------------------------
# Fisher z-transform CI for IC vectors
# ---------------------------------------------------------------------------


def _fisher_z_ci(
    ic_vector: np.ndarray,
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """95% CI for Spearman IC via Fisher z-transform.

    Exact asymptotic CI equivalent to the bootstrap limit as n → ∞.
    O(p) vs O(n_boot × n × p) for block bootstrap. No RNG, no memory pressure.

    The circular block bootstrap it replaces had a pre-ranking bug: it resampled
    globally pre-ranked values instead of resampling raw observations and re-ranking
    within each sample, producing CIs that were systematically too narrow.

    Returns NaN arrays when n < 4 (arctanh undefined); upstream min_reliable_n gate
    already excludes these, but defensive here.
    """
    if n < 4:
        nan = np.full_like(ic_vector, np.nan, dtype=float)
        return nan, nan.copy()
    z = np.arctanh(np.clip(ic_vector, -1 + 1e-10, 1 - 1e-10))
    se = 1.0 / np.sqrt(n - 3)
    return np.tanh(z - _Z95 * se), np.tanh(z + _Z95 * se)


# ---------------------------------------------------------------------------
# Vectorized IC computation
# ---------------------------------------------------------------------------


def _vectorized_ic(ranks_X: np.ndarray, ranks_Y: np.ndarray) -> np.ndarray:
    """Vectorized Spearman IC via Pearson on pre-ranked inputs.

    Args:
        ranks_X: Shape [n_obs, n_features] -- pre-ranked.
        ranks_Y: Shape [n_obs] -- pre-ranked.

    Returns:
        ic_vector: Shape [n_features].
    """
    n = ranks_X.shape[0]
    if n < 2:
        return np.zeros(ranks_X.shape[1])
    X_c = ranks_X - ranks_X.mean(axis=0)
    Y_c = ranks_Y - ranks_Y.mean()
    denom = np.sqrt((X_c**2).sum(axis=0) * (Y_c**2).sum())
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 1e-10, (X_c * Y_c[:, None]).sum(axis=0) / denom, 0.0)


def compute_ic_vectorized(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Compute vectorized Spearman IC between each column of X and y.

    Public wrapper around _vectorized_ic that accepts raw (unranked) inputs
    and handles ranking internally. Equivalent to scipy.stats.spearmanr(X[:,j], y)
    for each feature j, but computed simultaneously across all features via
    vectorized Pearson-on-ranks.

    Args:
        X: Shape [n_obs, n_features] -- raw feature values (not pre-ranked).
        y: Shape [n_obs] -- raw return vector (not pre-ranked).

    Returns:
        ic_vector: Shape [n_features] -- Spearman IC per feature.
    """
    ranks_X = rankdata(X, axis=0)
    ranks_y = rankdata(y)
    return _vectorized_ic(ranks_X, ranks_y)


def _expand(nd_arr: np.ndarray, mask: np.ndarray, n: int) -> np.ndarray:
    """Scatter nd_arr (non-degenerate features) into a NaN-filled n-length float array."""
    out = np.full(n, np.nan)
    out[mask] = nd_arr
    return out


def _nan_to_none(v: float) -> float | None:
    return None if np.isnan(v) else float(v)


def _p_values_from_ic(ic_vector: np.ndarray, n: int) -> np.ndarray:
    """Two-tailed p-values from IC via t-approximation.

    t = ic * sqrt((n-2) / max(1 - ic^2, 1e-10)), df = n-2.
    """
    t_stat = ic_vector * np.sqrt((n - 2) / np.maximum(1 - ic_vector**2, 1e-10))
    return 2.0 * (1.0 - t_dist.cdf(np.abs(t_stat), df=n - 2))


# ---------------------------------------------------------------------------
# IC Sharpe computation
# ---------------------------------------------------------------------------


def _hac_sharpe_nd(
    window_ics: np.ndarray,
    max_lag: int,
    mean_ic: np.ndarray | None = None,
    var0: np.ndarray | None = None,
) -> np.ndarray:
    """Newey-West Bartlett-kernel HAC-corrected IC Sharpe.

    Args:
        window_ics: [n_windows, n_features] IC values per rolling window.
        max_lag: Bartlett-kernel max lag K. K=0 returns naive Sharpe.
        mean_ic: Pre-computed column means (optional; computed internally if absent).
        var0: Pre-computed population variance per feature (optional; avoids recomputation
              when the caller already holds mean_ic and std_ic).

    Returns:
        sharpe_hac: [n_features]. Equal to naive Sharpe when max_lag=0 or
        when the IC series has zero autocorrelation. Always <= naive Sharpe
        for positively autocorrelated IC series (inflation floored at 1).
    """
    n, p = window_ics.shape
    if mean_ic is None:
        mean_ic = window_ics.mean(axis=0)
    if var0 is None:
        var0 = ((window_ics - mean_ic) ** 2).mean(axis=0)

    if max_lag == 0 or n < max_lag + 2:
        hac_std = np.sqrt(var0)
        return np.where(hac_std > 1e-10, mean_ic / hac_std, 0.0)

    demeaned = window_ics - mean_ic
    inflation = np.ones(p)
    for k in range(1, max_lag + 1):
        gamma_k = (demeaned[k:] * demeaned[:-k]).mean(axis=0)
        rho_k = np.where(var0 > 1e-12, gamma_k / var0, 0.0)
        inflation += 2.0 * (1.0 - k / (max_lag + 1)) * rho_k

    inflation = np.maximum(inflation, 1.0)  # can't be more precise than i.i.d.
    hac_std = np.sqrt(var0 * inflation)
    return np.where(hac_std > 1e-10, mean_ic / hac_std, 0.0)


def _compute_ic_rolling_metrics(
    X_sub: np.ndarray,
    returns_sub: np.ndarray,
    scale_idx: int,
    complete_mask: np.ndarray,
    config: SharpeWindowConfig,
    non_degenerate_mask: np.ndarray,
    n_total_features: int,
    stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Compute IC Sharpe, HAC Sharpe, Sortino, and win rate via rolling non-overlapping windows.

    Gate: n_windows_possible >= sharpe_min_windows.
    Returns NaN arrays when gate not met.

    IC Sharpe     = mean(window_ICs) / std(window_ICs)                       [symmetric]
    IC Sharpe HAC = mean(window_ICs) / (std(window_ICs) * sqrt(NW_inflation)) [autocorr-adjusted]
    IC Sortino    = mean(window_ICs) / semi_dev(neg windows)                  [downside only]
                    NaN when no windows have IC < 0 (ratio undefined)
    IC win rate   = fraction of windows where IC > 0                          [stability]

    Args:
        stride: Subsampling stride used to create X_sub/returns_sub. sharpe_window_size
                from APR is in RAW bars, so we divide by stride to get subsampled bars.

    Returns: (sharpe_arr, sharpe_hac_arr, sortino_arr, win_rate_arr, n_windows)
    """
    # sharpe_window_size is in RAW bars; convert to SUBSAMPLED bars via floor division.
    # Precision loss: e.g., 1999 raw bars with stride=10 → 199 subsampled bars (10% loss from 200).
    # Floor division ensures we never exceed available subsampled data.
    sharpe_window_size_raw = config.sharpe_window_size
    sharpe_window_size = max(1, sharpe_window_size_raw // stride)
    sharpe_min_windows = config.sharpe_min_windows

    nan_result = np.full(n_total_features, np.nan)
    n_windows = 0

    if complete_mask.sum() < 2:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    X_aligned = X_sub[complete_mask]
    Y_aligned = returns_sub[complete_mask, scale_idx]

    n = len(X_aligned)
    n_windows_possible = n // sharpe_window_size
    if n_windows_possible < sharpe_min_windows:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    window_ics_list = []
    for w in range(n_windows_possible):
        start = w * sharpe_window_size
        end = start + sharpe_window_size
        wx = X_aligned[start:end][:, non_degenerate_mask]
        wy = Y_aligned[start:end]
        if len(wx) < 2:
            continue
        rx = rankdata(wx, axis=0)
        ry = rankdata(wy)
        window_ics_list.append(_vectorized_ic(rx, ry))

    n_windows = len(window_ics_list)
    if n_windows < sharpe_min_windows:
        return nan_result, nan_result, nan_result, nan_result, n_windows

    window_ics = np.array(window_ics_list)  # [n_windows, n_non_degenerate]
    mean_ic = window_ics.mean(axis=0)
    var0 = ((window_ics - mean_ic) ** 2).mean(axis=0)
    std_ic = np.sqrt(var0)

    sharpe_nd = np.where(std_ic > 1e-10, mean_ic / std_ic, 0.0)
    sharpe_hac_nd = _hac_sharpe_nd(window_ics, config.hac_max_lag, mean_ic=mean_ic, var0=var0)

    # Sortino: penalise only negative-IC windows (target = 0)
    # NaN per feature when that feature has no negative windows (ratio undefined)
    neg_mask = window_ics < 0  # [n_windows, n_non_degenerate]
    sum_neg = neg_mask.sum(axis=0)  # reused for both gate and denominator
    semi_dev = np.where(
        sum_neg > 0,
        np.sqrt(np.where(neg_mask, window_ics**2, 0.0).sum(axis=0) / sum_neg),
        np.nan,
    )
    sortino_nd = np.where(semi_dev > 1e-10, mean_ic / semi_dev, np.nan)

    win_rate_nd = (window_ics > 0).mean(axis=0)

    n = n_total_features
    return (
        _expand(sharpe_nd, non_degenerate_mask, n),
        _expand(sharpe_hac_nd, non_degenerate_mask, n),
        _expand(sortino_nd, non_degenerate_mask, n),
        _expand(win_rate_nd, non_degenerate_mask, n),
        n_windows,
    )
