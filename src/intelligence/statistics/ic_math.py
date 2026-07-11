"""Shared IC (Information Coefficient) math -- circular block bootstrap CI (production,
Component A / todo 091), the superseded Fisher z-transform CI (kept for
services/ensemble_ic_engine.py and scripts/ops/corpus/ops_oos_holdout_eval.py, which
stay on it this phase -- see 143.1-CONTEXT.md resolved item 3), vectorized Spearman IC,
HAC-corrected rolling Sharpe, and p-values.

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

import math
from typing import Protocol

import numpy as np
from scipy.stats import norm, rankdata
from scipy.stats import t as t_dist
from statsmodels.stats.multitest import multipletests

_Z95 = 1.959963985  # norm.ppf(0.975) — 95% two-tailed critical value


def _arctanh_clip(x: np.ndarray | float) -> np.ndarray | float:
    """Fisher z-transform with the standard epsilon clip against +/-1 (arctanh is
    undefined exactly at +/-1). Shared by every Fisher-z-based function in this module.
    """
    return np.arctanh(np.clip(x, -1 + 1e-10, 1 - 1e-10))


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
    z = _arctanh_clip(ic_vector)
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


def _circular_shift_null(
    Y: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Circularly shift Y by a random offset in [1, len(Y)-1] (todo 071 / L4-2).

    Destroys alignment with any paired X while preserving Y's own autocorrelation/
    spectral structure exactly -- every value present, same adjacency structure up
    to the wrap point. This is what makes the result a meaningful null for an
    autocorrelated series; an i.i.d. shuffle would destroy the autocorrelation the
    stride-subsampling/HAC design exists to handle, producing an easier strawman null.

    Excludes offset=0 (the identity permutation, which would leave X-Y aligned).
    n < 2 has no valid nonzero offset; returns a copy of Y unchanged.
    """
    n = len(Y)
    if n < 2:
        return Y.copy()
    offset = int(rng.integers(1, n))
    return np.roll(Y, offset)


# ---------------------------------------------------------------------------
# Circular block bootstrap CI for IC vectors (production CI, todo 091 / Component A)
# ---------------------------------------------------------------------------


def _circular_block_bootstrap_ic(
    X_raw: np.ndarray,
    Y_raw: np.ndarray,
    block_size: int,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Circular block bootstrap for IC confidence intervals -- the production CI,
    restoring the function removed in commit c6f5056b with its pre-ranking bug fixed.

    Replaces `_fisher_z_ci` as the production CI at ic_engine.py's 3 call sites: the
    2026-07-09 empirical-null diagnostic (`ops_ic_null_calibration.py`) found the
    Fisher-z analytic CI empirically miscalibrated (38% SUSPECT rate, 11/29 evaluated
    cells across 4/8 (tf, is_pooled) strata) -- the asymptotic SE assumption does not
    hold at this corpus's actual autocorrelation/regime structure. `_fisher_z_ci`
    itself is left unchanged for its remaining callers (services/ensemble_ic_engine.py,
    scripts/ops/corpus/ops_oos_holdout_eval.py) -- a stated, not silent, scope boundary
    for this phase (143.1-CONTEXT.md resolved item 3).

    CRITICAL correctness requirement (the exact bug that caused the original 2026-06-26
    removal): inputs are RAW, UNRANKED paired observations, not pre-ranked values.
    Spearman IC is defined on ranks *within the sample being correlated* -- reusing
    global ranks computed once outside the bootstrap loop and indexing into them with a
    non-contiguous resampled block silently narrows the resulting CI (the resampled
    subset's local rank order differs from its rank order in the full series). This
    function re-ranks the resampled subset EVERY iteration via `rankdata` before calling
    `_vectorized_ic` -- that re-rank is the fix, not a cosmetic rename.

    Circular-wrap block index construction (`starts = rng.integers(0, n, n_blocks);
    idx = (starts[:, None] + offsets).ravel()[:n] % n`) is unchanged from the removed
    version -- blocks may wrap past the end of the series (`% n`), eliminating boundary
    discontinuities at the series edges (D-15). This mechanic was never the bug; only
    the missing re-rank step was.

    Per-iteration allocation (`for b in range(n_boot): ...`), NOT a single
    `(n_boot, n_blocks, block_size)` broadcast: at production scale (n ~ 469K,
    block_size=10) the broadcast form allocates ~7.5 GB per ProcessPoolExecutor worker,
    OOM-killing the process under parallel execution. This loop form allocates
    ~3.75 MB per iteration.

    Args:
        X_raw: Shape [n_obs, n_features] -- RAW (unranked) feature matrix.
        Y_raw: Shape [n_obs] -- RAW (unranked) return vector.
        block_size: Number of consecutive observations per bootstrap block. From APR:
            alpha.ic.bootstrap_block_size.{tf}.
        n_boot: Number of bootstrap replicates. From APR: alpha.ic.bootstrap_resamples.
        rng: numpy random Generator, seeded deterministically per (symbol/cell, run)
            for reproducibility across ic_engine invocations -- never an unseeded or
            module-global Generator (ProcessPoolExecutor workers must derive their own
            seed; see services/ic_engine.py's _derive_worker_rng_seed()).

    Returns:
        (ci_lower, ci_upper): Each shape [n_features]; 95% CI via percentile method.
    """
    n, p = X_raw.shape
    n_blocks = math.ceil(n / block_size)
    boot_ics = np.zeros((n_boot, p))
    offsets = np.arange(block_size)

    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        ranks_X_boot = rankdata(X_raw[idx], axis=0)
        ranks_Y_boot = rankdata(Y_raw[idx])
        boot_ics[b] = _vectorized_ic(ranks_X_boot, ranks_Y_boot)

    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


def vol_normalized_return(
    return_x: np.ndarray, true_range_pct: np.ndarray, eps: float = 1e-10
) -> np.ndarray:
    """Vol-normalized return target: return_x / true_range_pct, epsilon-guarded.

    Component F (todo 097, Phase 143.1-03): an alternative POOLED-strata IC target
    that normalizes the raw forward-return array by `true_range_pct` -- already
    loaded in `ic_engine.py`'s `_compute_cross_sectional_tf` query (raw,
    non-z-scored). Deliberately NOT `atr_z` (already z-scored, unusable as a
    sigma-scale denominator) and NOT a new rolling-window vol computation (no
    existing column; would require new SQL window-function work per
    143.1-CONTEXT.md/RESEARCH.md resolved item 8 / Assumption A1).

    Epsilon guard matches `src/intelligence/feature_factory.py`'s `_ret_vol_ratio()`
    convention (eps=1e-10 default, returns 0.0 rather than inf/nan on a
    near-zero denominator) -- vectorized across the whole array instead of
    guarding one scalar at a time.

    This is a measurement-time diagnostic helper only -- it does not replace the
    production return target (`return_fast/mid/slow/extended` stay raw in
    `forward_returns`/`feature_ic_scores`). See
    `scripts/ops/alpha/ops_vol_normalized_target_ab.py` for the explicit A/B this
    feeds; per the locked validation contract (143.1-CONTEXT.md Component F), this
    is never a silent production swap -- retire the transform if vol-normalized
    rankings are materially identical to the raw-return baseline.

    Args:
        return_x: Shape [n_obs] -- raw forward return array (any `_SCALES` column,
            e.g. `returns_scale` in `_compute_cross_sectional_tf`).
        true_range_pct: Shape [n_obs] -- raw (non-z-scored) `true_range_pct` column,
            already present in `ic_engine.py`'s `X_raw`/`X_sub` at
            `_FEATURE_NAMES.index("true_range_pct")`, sliced to the same rows as
            `return_x` (e.g. via the same `valid_mask`).
        eps: Epsilon guard threshold, matching `_ret_vol_ratio`'s default.

    Returns:
        Shape [n_obs] -- `return_x / true_range_pct`, with 0.0 wherever
        `abs(true_range_pct) < eps`.
    """
    return_x = np.asarray(return_x, dtype=np.float64)
    true_range_pct = np.asarray(true_range_pct, dtype=np.float64)
    guard = np.abs(true_range_pct) >= eps
    out = np.zeros_like(return_x, dtype=np.float64)
    out[guard] = return_x[guard] / true_range_pct[guard]
    return out


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


def _p_values_from_ic(ic_vector: np.ndarray, n: int, df: int | None = None) -> np.ndarray:
    """Two-tailed p-values from IC via t-approximation.

    t = ic * sqrt(df / max(1 - ic^2, 1e-10)).

    df defaults to n-2 (the plain-correlation case). Pass an explicit df to account
    for additional parameters fit via OLS before this correlation was computed (e.g.
    partial_spearman_ic's df = n - k - 2 for k control variables) rather than
    hand-rolling this same t-approximation a second time with a different df.
    """
    if df is None:
        df = n - 2
    t_stat = ic_vector * np.sqrt(df / np.maximum(1 - ic_vector**2, 1e-10))
    return 2.0 * (1.0 - t_dist.cdf(np.abs(t_stat), df=df))


# ---------------------------------------------------------------------------
# Two-sample IC difference test (todo 069 / measurement-ic-engine.md OQ7)
# ---------------------------------------------------------------------------


def fisher_z_difference_p(
    ic_a: float,
    n_a: float,
    ic_b: float,
    n_b: float,
) -> float:
    """Two-sided p-value for the difference between two independent IC estimates.

    Standard two-independent-correlations difference test via Fisher z-transform:
    z_diff = (arctanh(ic_a) - arctanh(ic_b)) / SE, SE = sqrt(1/(n_a-3) + 1/(n_b-3)),
    p = 2 * (1 - Phi(|z_diff|)) under the standard normal.

    Conservative under positive dependence: this formula assumes ic_a and ic_b are
    estimated on independent samples. When the two estimates are measured on the same
    bars with largely overlapping alpha constructions (e.g. two ensemble weight_version
    variants scored on the same corpus), their estimation errors are positively
    correlated, so the true standard error of the difference is smaller than this
    formula assumes -- the returned p-value is therefore an overestimate, biased toward
    NOT rejecting H0. That is the intended, safe direction for this use (see
    docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md).

    Returns NaN when n_a <= 3 or n_b <= 3 (the SE term is undefined -- same n>3
    requirement as _fisher_z_ci's arctanh variance approximation).
    """
    if n_a <= 3 or n_b <= 3:
        return float("nan")
    z_a = _arctanh_clip(ic_a)
    z_b = _arctanh_clip(ic_b)
    se = np.sqrt(1.0 / (n_a - 3) + 1.0 / (n_b - 3))
    z_diff = (z_a - z_b) / se
    return float(2.0 * (1.0 - norm.cdf(np.abs(z_diff))))


# ---------------------------------------------------------------------------
# Shared BH-FDR correction (todo 069)
# ---------------------------------------------------------------------------


def apply_bh_fdr(p_values: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction over one family of p-values.

    Thin, deliberately minimal wrapper around statsmodels' multipletests: this
    "collect p-values -> one multipletests call -> scatter reject/corrected-p back by
    index" shape was independently hand-rolled at three call sites (services/ic_engine.py,
    services/ensemble_ic_engine.py, scripts/ops/corpus/ops_oos_holdout_eval.py's
    _apply_corpus_fdr) before this extraction. Only the multipletests call itself is
    shared here, not the scatter-back-into-a-container step -- each caller's result
    container shape differs (flat list of dicts, dict keyed by stratum, etc.), so forcing
    one scatter convention on all of them would be a worse fit than leaving that one line
    local to each caller.

    Returns (reject, p_corrected) as parallel arrays in the same order as p_values.
    Returns two empty arrays for an empty input (no family to correct).
    """
    if not p_values:
        return np.array([], dtype=bool), np.array([], dtype=float)
    reject, p_corrected, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    return reject, p_corrected


# ---------------------------------------------------------------------------
# Shared condition-number gate for any Sigma^-1/lstsq solve on an estimated matrix
# ---------------------------------------------------------------------------


def check_condition_number(matrix: np.ndarray, condition_max: float) -> tuple[bool, float]:
    """Ill-conditioning gate shared by every linear solve against an estimated
    (not population) matrix in this codebase: mean_variance_weights()'s Sigma^-1 .
    ic_shrunk combination and partial_spearman_ic()'s rank-OLS residualization both
    need the identical "is this solve numerically trustworthy" check before trusting
    a result computed against noisy, estimated data -- previously duplicated
    independently at both call sites.

    Returns (is_ok, cond): cond (2-norm, np.linalg.cond default) is always returned,
    even on gate failure, so callers can log the fallback reason; is_ok is False
    when cond is non-finite or exceeds condition_max.
    """
    cond = float(np.linalg.cond(matrix))
    return (np.isfinite(cond) and cond <= condition_max), cond


# ---------------------------------------------------------------------------
# Partial (residual) Spearman IC -- todo 037 interaction primitives pilot
# ---------------------------------------------------------------------------


def partial_spearman_ic(
    x: np.ndarray,
    y: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
) -> tuple[float, float, int]:
    """Partial Spearman IC of x vs y, controlling for one or more control variables.

    Residual method: rank-transform x, y, and each control column; regress (centered)
    ranks_x and ranks_y on (centered) ranks_controls via OLS; the partial IC is the
    Pearson correlation of the two residual vectors (via _vectorized_ic, the same
    Pearson-on-ranks primitive used everywhere else in this module). Equivalent to
    the classic single-control partial-correlation formula and generalizes cleanly
    to k>1 controls -- every Renaissance interaction primitive has exactly 2 parent
    atomics (feature_registry.parent_features), so k=2 is the pilot's actual shape.

    Working with centered ranks (intercept-free regression) improves numerical
    stability without changing the mathematical result. Both residual regressions
    share one design matrix (ranks_controls_c), so they're solved in a single
    np.linalg.lstsq call against both right-hand sides at once rather than two
    independent factorizations of the same matrix.

    p-value uses the same t-approximation as _p_values_from_ic (shared, not
    reimplemented), with degrees of freedom reduced by k (one parameter fit per
    control): df = n - k - 2.

    Guards against multicollinear control sets via the same check_condition_number()
    gate mean_variance_weights() uses -- an ill-conditioned design matrix produces
    numerically unstable residuals, not a genuine partial correlation, so this
    returns NaN rather than a garbage number.

    Returns (partial_ic, p_value, n) as (nan, nan, n) when: n is too small for the
    adjusted df (n < k + 4); the control design matrix's condition number exceeds
    condition_max (see alpha.ic.partial_control_condition_max); or the residual
    vectors are degenerate (near-zero variance after removing the controls' shared
    variance -- no real correlation left to measure, same "unmeasurable" class as
    the other two guards, not a genuine 0.0 partial IC with p=1.0).
    """
    n = len(x)
    if controls.ndim == 1:
        controls = controls.reshape(-1, 1)
    k = controls.shape[1]
    if n < k + 4:
        return float("nan"), float("nan"), n

    ranks_x = rankdata(x)
    ranks_y = rankdata(y)
    ranks_controls = rankdata(controls, axis=0)

    # Center the data for numerical stability (removes need for explicit intercept)
    ranks_x_c = ranks_x - ranks_x.mean()
    ranks_y_c = ranks_y - ranks_y.mean()
    ranks_controls_c = ranks_controls - ranks_controls.mean(axis=0)

    cond_ok, _cond = check_condition_number(ranks_controls_c, condition_max)
    if not cond_ok:
        return float("nan"), float("nan"), n

    coefs, _, _, _ = np.linalg.lstsq(
        ranks_controls_c, np.column_stack([ranks_x_c, ranks_y_c]), rcond=None
    )
    resid_x = ranks_x_c - ranks_controls_c @ coefs[:, 0]
    resid_y = ranks_y_c - ranks_controls_c @ coefs[:, 1]

    denom = np.sqrt((resid_x**2).sum() * (resid_y**2).sum())
    if denom < 1e-10:
        return float("nan"), float("nan"), n
    partial_ic = float(_vectorized_ic(resid_x.reshape(-1, 1), resid_y)[0])

    df = n - k - 2
    if df < 1:
        return partial_ic, float("nan"), n
    p_value = float(_p_values_from_ic(np.array([partial_ic]), n, df=df)[0])
    return partial_ic, p_value, n


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
