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
import warnings
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
from scipy.stats import norm, rankdata
from scipy.stats import t as t_dist
from statsmodels.stats.multitest import multipletests

_Z95 = 1.959963985  # norm.ppf(0.975) — 95% two-tailed critical value

# Tolerance for the CI-bracket boundary check in _clamp_ci_to_ic: how far a Fisher-z
# CI bound may fall outside [ci_lower, ci_upper] <=> ic before it is treated as
# float64 tanh/arctanh boundary noise (observed magnitude ~8e-11 at IC=+-1.0) rather
# than a genuine bug. 1e-6 sits many orders above that observed noise floor and many
# orders below any real statistical discrepancy -- a numerical-noise guard, not a
# tunable (APR-exempt, same reasoning as compute_ic_vectorized's degenerate-std guard).
_CI_BOUNDARY_TOL = 1e-6


def _arctanh_clip(x: np.ndarray | float) -> np.ndarray | float:
    """Fisher z-transform with the standard epsilon clip against +/-1 (arctanh is
    undefined exactly at +/-1). Shared by every Fisher-z-based function in this module.
    """
    return np.arctanh(np.clip(x, -1 + 1e-10, 1 - 1e-10))


def _clamp_ci_to_ic(
    ci_lower: np.ndarray | float,
    ci_upper: np.ndarray | float,
    ic: np.ndarray | float,
    tol: float = _CI_BOUNDARY_TOL,
) -> tuple[np.ndarray, np.ndarray]:
    """Clamp a Fisher-z CI bracket so it encompasses its point estimate, but only
    when the pre-clamp violation is genuine float64 boundary noise.

    _fisher_z_ci's tanh/arctanh round-trip can land ci_upper a few 1e-11 below (or
    ci_lower a few 1e-11 above) the point estimate at the +-1.0 saturation boundary
    -- expected numerical noise, not a statistical error. This function absorbs only
    that: if any element's ci_lower exceeds ic, or ic exceeds ci_upper, by more than
    `tol`, it raises loudly instead of silently swallowing the discrepancy, because a
    violation that large means _fisher_z_ci produced an invalid bracket (e.g. a sign
    error) -- a real bug that must not be masked as a "numerical precision safeguard"
    ("silent wrong answers are worse than loud crashes").

    Elementwise over arrays (or scalars); every caller of _fisher_z_ci gets this
    check for free rather than reimplementing it per call site.

    Raises:
        ValueError: if either bound is violated by more than `tol` anywhere.
    """
    ci_lower = np.asarray(ci_lower, dtype=np.float64)
    ci_upper = np.asarray(ci_upper, dtype=np.float64)
    ic = np.asarray(ic, dtype=np.float64)
    lower_violation = ci_lower - ic
    upper_violation = ic - ci_upper
    max_lower = np.nanmax(lower_violation) if lower_violation.size else -np.inf
    max_upper = np.nanmax(upper_violation) if upper_violation.size else -np.inf
    if max_lower > tol:
        raise ValueError(
            f"_fisher_z_ci produced ci_lower > ic by {max_lower!r} (worst element), "
            f"exceeding tolerance {tol!r} -- this is larger than float64 boundary "
            "noise and indicates a real bug upstream, not a numerical-precision "
            "artifact."
        )
    if max_upper > tol:
        raise ValueError(
            f"_fisher_z_ci produced ci_upper < ic by {max_upper!r} (worst element), "
            f"exceeding tolerance {tol!r} -- this is larger than float64 boundary "
            "noise and indicates a real bug upstream, not a numerical-precision "
            "artifact."
        )
    return np.clip(ci_lower, -1.0, ic), np.clip(ci_upper, ic, 1.0)


class SharpeWindowConfig(Protocol):
    """Duck-typed shape _compute_ic_rolling_metrics needs from a frozen IC config
    dataclass. Both ICEngineConfig and EnsembleICConfig satisfy this structurally.

    sharpe_window_size_subsampled (todo 096, APR key
    alpha.ic.sharpe_window_size_subsampled): fixed window size expressed directly in
    SUBSAMPLED bars. Deliberately NOT derived from a raw-bar constant divided by
    stride (the old alpha.ic.sharpe_window_size semantics, now deprecated) -- that
    let each window's data density collapse as stride grew, mechanically deflating
    ic_sharpe at longer lookaheads by ~sqrt(window_size_ratio) with zero real signal
    decay. See scripts/analysis/ic_sharpe_stride_bias_check.py for the Monte Carlo
    proof and .planning/todos/pending/096-*.md for the full writeup.
    """

    sharpe_window_size_subsampled: int
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

    The returned bracket is always clamped to encompass ic_vector via
    _clamp_ci_to_ic (raises loudly if a bound is invalid by more than float64
    boundary noise) -- every caller gets this guard automatically instead of each
    reimplementing it (todo 109).
    """
    if n < 4:
        nan = np.full_like(ic_vector, np.nan, dtype=float)
        return nan, nan.copy()
    z = _arctanh_clip(ic_vector)
    se = 1.0 / np.sqrt(n - 3)
    ci_lower = np.tanh(z - _Z95 * se)
    ci_upper = np.tanh(z + _Z95 * se)
    return _clamp_ci_to_ic(ci_lower, ci_upper, ic_vector)


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
    max_workers: int = 1,
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

    Threading (todo 131, 2026-07-17): the RNG draw (`rng.integers`) that determines
    each iteration's resampled block indices is cheap and MUST stay strictly serial --
    it is the only stateful, order-dependent step, and correctness/reproducibility
    depend on drawing in the same order regardless of max_workers. The expensive step
    (re-rank + IC on the resampled (n, p) block) is pure and independent per iteration,
    so it's dispatched to a bounded thread pool in max_workers-sized batches: draw a
    batch of indices serially, hand the batch to the pool, write results back at their
    absolute iteration index (never appended in completion order), repeat. Benchmarked
    on this corpus's largest cross-sectional cell shape (n=361674, p=154): ~5x wall
    time at max_workers=16 on a 24-core host -- numpy/scipy's sort releases the GIL
    enough for real parallelism without ProcessPoolExecutor's per-worker array-copy
    cost. Batching (not a single `executor.map` over all n_boot indices) bounds peak
    memory to max_workers index arrays at a time, not n_boot of them (~3.75 MB x 2000
    would be ~7.5 GB otherwise). max_workers=1 (the default) takes the plain serial
    path -- bit-for-bit identical to the pre-threading implementation, so every
    existing caller is unaffected unless it explicitly opts in.

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
        max_workers: Thread pool size for the re-rank + IC step. 1 (default) runs
            fully serial. Callers already running inside a ProcessPoolExecutor pool
            (ic_engine.py's per-symbol path) must keep this at 1 -- the pool already
            saturates available cores; threading on top would oversubscribe, not
            speed up. Only safe to raise where nothing else is contending for cores
            (ic_engine.py's cross-sectional path, which runs after the per-symbol
            pool has already shut down). From APR:
            infra.ic_engine.cross_sectional_bootstrap_threads.

    Returns:
        (ci_lower, ci_upper): Each shape [n_features]; 95% CI via percentile method.
    """
    n, p = X_raw.shape
    n_blocks = math.ceil(n / block_size)
    boot_ics = np.zeros((n_boot, p))
    offsets = np.arange(block_size)

    def _draw_idx() -> np.ndarray:
        starts = rng.integers(0, n, size=n_blocks)
        return (starts[:, None] + offsets).ravel()[:n] % n

    def _resample_ic(idx: np.ndarray) -> np.ndarray:
        ranks_X_boot = rankdata(X_raw[idx], axis=0)
        ranks_Y_boot = rankdata(Y_raw[idx])
        return _vectorized_ic(ranks_X_boot, ranks_Y_boot)

    if max_workers <= 1:
        for b in range(n_boot):
            boot_ics[b] = _resample_ic(_draw_idx())
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for b in range(0, n_boot, max_workers):
                batch_end = min(b + max_workers, n_boot)
                # Serial draw, in order -- the only part that must never run
                # concurrently (see docstring). pool.map() yields results in
                # submission order (stdlib-guaranteed), not completion order.
                batch_idx = [_draw_idx() for _ in range(b, batch_end)]
                boot_ics[b:batch_end] = list(pool.map(_resample_ic, batch_idx))

    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


def circular_block_bootstrap_ic_serial(
    X_raw: np.ndarray,
    Y_raw: np.ndarray,
    block_size: int,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-symbol call sites' entry point -- always serial, no `max_workers` knob.

    These call sites already run inside `main()`'s per-symbol `ProcessPoolExecutor`
    pool; threading on top would oversubscribe cores, not speed anything up (todo
    131). Previously enforced by a `max_workers=1` argument + comment repeated at
    each call site -- structurally enforced here instead: this wrapper has no
    `max_workers` parameter to accidentally raise, so a future edit that copies the
    cross-sectional call site's `max_workers=config.cross_sectional_bootstrap_threads`
    into a per-symbol call site can't compile against this signature.
    """
    return _circular_block_bootstrap_ic(X_raw, Y_raw, block_size, n_boot, rng, max_workers=1)


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
# IC decomposition: directional accuracy vs magnitude alignment
# (Component B, todo 090, Phase 143.1 Plan 05)
# ---------------------------------------------------------------------------


def sign_hit_rate(X_raw: np.ndarray, y_raw: np.ndarray) -> np.ndarray:
    """Directional-accuracy component of IC decomposition: fraction of bars where
    sign(prediction) == sign(realized return), per feature.

    Complements magnitude_conditional_ic to distinguish "gets the direction right"
    from "gets the magnitude right when it matters" -- sharpens Phase 143's decay
    monitors by decomposing a single IC value into these two components. Diagnostic
    only, no eligibility/gate predicate reads this column.

    NaN-safe via np.sign's own zero-maps-to-zero convention: a bar where the
    prediction or the realized return is exactly zero has an undefined sign, so it
    is excluded from both the numerator and the denominator (not scored as either a
    hit or a miss). A feature with zero valid (nonzero-sign) observations returns
    NaN for that column rather than a spurious 0/0-as-0.0.

    Args:
        X_raw: Shape [n_obs, n_features] -- raw (unranked) feature/prediction values.
        y_raw: Shape [n_obs] -- raw (unranked) realized return values.

    Returns:
        Shape [n_features] -- sign_hit_rate in [0, 1] per feature; NaN where a
        feature has zero valid (nonzero-sign) observations.
    """
    sign_x = np.sign(X_raw)
    sign_y = np.sign(y_raw)[:, None]
    valid = (sign_x != 0) & (sign_y != 0) & np.isfinite(sign_x) & np.isfinite(sign_y)
    match = (sign_x == sign_y) & valid
    n_valid = valid.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n_valid > 0, match.sum(axis=0) / np.maximum(n_valid, 1), np.nan)


def magnitude_conditional_ic(
    X_raw: np.ndarray,
    y_raw: np.ndarray,
    percentile: float,
) -> np.ndarray:
    """Magnitude-alignment component of IC decomposition: IC recomputed over the
    subset of bars where |prediction| is above a percentile threshold, per feature.

    Reuses _vectorized_ic on the re-ranked subset -- never re-derives Spearman via
    scipy.stats.spearmanr (RESEARCH Don't Hand-Roll). Matches the bootstrap's
    re-rank discipline (_circular_block_bootstrap_ic): Spearman IC is defined on
    ranks *within the sample being correlated*, so the subset is re-ranked from
    scratch rather than reusing global ranks computed on the full sample.

    percentile is a per-feature threshold (np.percentile(|X|, percentile, axis=0)
    computed independently per column) -- a feature with a different scale/
    distribution gets its own magnitude cutoff rather than a shared absolute value.

    Per-feature Python loop (not vectorized across features): each feature's
    magnitude-subset mask differs, so the subset size/composition can't be
    expressed as one shared boolean mask across columns. This loop runs once per
    feature per (tf, regime, scale) cell (~150 iterations), not per observation --
    not the "never log per-row in a corpus loop" pattern this codebase forbids.

    Args:
        X_raw: Shape [n_obs, n_features] -- raw (unranked) feature/prediction values.
        y_raw: Shape [n_obs] -- raw (unranked) realized return values.
        percentile: Selects the top (100 - percentile)% of bars by |X| per feature
            (e.g. percentile=75.0 selects the top quartile by magnitude).

    Returns:
        Shape [n_features] -- magnitude-conditional IC per feature; NaN where the
        thresholded subset has fewer than 2 observations, is degenerate (zero
        variance in either X or y within the subset), or the input is NaN-only.
    """
    n_features = X_raw.shape[1]
    out = np.full(n_features, np.nan)
    abs_X = np.abs(X_raw)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # All-NaN columns are a legitimate degenerate case handled by the mask.sum()<2
        # guard below, not a bug -- suppress numpy's "All-NaN slice encountered"
        # RuntimeWarning rather than letting it leak into corpus-run logs.
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        thresholds = np.nanpercentile(abs_X, percentile, axis=0)
    for j in range(n_features):
        col_x = X_raw[:, j]
        col_valid = np.isfinite(col_x) & np.isfinite(y_raw)
        mask = col_valid & (abs_X[:, j] >= thresholds[j])
        if mask.sum() < 2:
            continue
        rx = rankdata(col_x[mask]).reshape(-1, 1)
        ry = rankdata(y_raw[mask])
        out[j] = _vectorized_ic(rx, ry)[0]
    return out


# ---------------------------------------------------------------------------
# Anytime-valid e-values on IC sign (Component C, todo 079, Phase 143.1 Plan 06)
# ---------------------------------------------------------------------------

# Fixed alternative-hypothesis probability for the IC-sign likelihood-ratio
# e-value: H0 (sign is a fair coin, P(matches tested direction)=0.5 -- reruns
# are pure noise) vs H1 (P(matches)=p_alt, a persistently directional feature).
# [conventional] statistical concept definition, not an APR key -- this pilot's
# threat model (143.1-06-PLAN.md, T-143.1-06-V5) explicitly disposes "no new
# APR keys or external input." 0.75 is a moderate, conservative assumed effect
# size: large enough to accumulate promotion-grade evidence within a bounded
# number of corpus reruns, not so large it approaches a degenerate weight.
_E_VALUE_P_ALT = 0.75


def ic_sign_e_value_factor(ic_sign: int, p_alt: float = _E_VALUE_P_ALT) -> float:
    """Likelihood-ratio e-value factor for one run's IC-sign observation, testing
    the POSITIVE direction (sign matches == ic_sign > 0).

    This is Wald's SPRT likelihood ratio for a single Bernoulli trial: LR =
    P_H1(x) / P_H0(x). A likelihood ratio against a fixed simple alternative is
    itself a nonnegative e-variable under H0 by construction -- E_H0[LR] = 1
    exactly (P_H0(x)=0.5 for both outcomes, so E_H0[LR] = 0.5*(p_alt/0.5) +
    0.5*((1-p_alt)/0.5) = p_alt + (1-p_alt) = 1). Multiplying independent
    per-run e-value factors together therefore preserves E_H0[cumulative]<=1
    at every step (a nonnegative martingale under H0), which by Ville's
    inequality gives P(sup_t cumulative_t >= 1/alpha) <= alpha -- anytime-valid
    Type-I error control across an unbounded number of corpus reruns, unlike a
    classical p-value that must be recomputed fresh (and re-corrected) each run.

    Args:
        ic_sign: +1 (positive IC this run) or -1 (negative IC this run). Pass
            the RAW observed sign for a promotion test (testing "is this
            feature's IC persistently positive"); pass the negated sign to
            test the opposite (persistently negative) direction with the same
            function -- the demotion/promotion symmetry lives in
            update_cumulative_e_value's threshold comparison, not here.
        p_alt: Fixed alternative-hypothesis matching probability. See module
            docstring for why 0.75 and why not an APR key.

    Returns:
        e-value factor > 0: (p_alt / 0.5) when ic_sign matches the tested
        (positive) direction, ((1 - p_alt) / 0.5) when it doesn't.
    """
    matches_positive = ic_sign > 0
    return (p_alt / 0.5) if matches_positive else ((1.0 - p_alt) / 0.5)


def update_cumulative_e_value(
    prior_cumulative: float,
    ic_sign: int | None,
    p_alt: float = _E_VALUE_P_ALT,
) -> float:
    """Multiplicative anytime-valid update: cumulative_e_t = cumulative_e_{t-1}
    * e_t -- evidence compounds across corpus reruns instead of resetting each
    build (hardens the Concept Registry's "no re-roll on same corpus build"
    invariant into "no free re-roll on ANY build," todo 079).

    prior_cumulative=1.0 represents the neutral starting point (no evidence
    yet, i.e. the first-ever look at this cell) -- callers pass 1.0 when no
    prior feature_ic_scores row exists for this cell.

    ic_sign=None (a degenerate/unmeasurable cell this run -- e.g. zero-variance
    feature, insufficient n) contributes NO evidence: the cumulative value is
    returned unchanged rather than penalized as if it were a genuine null
    observation. A missing measurement is not the same as evidence of no
    signal.

    Promotion/demotion symmetry (todo 079): callers compare the returned value
    against reciprocal thresholds -- cumulative > 1/alpha promotes (strong
    evidence FOR the tested direction); cumulative < alpha demotes (equally
    strong evidence AGAINST it). Both thresholds derive from the same single
    e-value process; no second process or column is needed.

    Args:
        prior_cumulative: The cumulative e-value from the immediately prior
            corpus run for this exact cell (same feature_name, symbol, tf,
            regime, lookahead_bars), or 1.0 if this is the first look.
        ic_sign: This run's observed IC sign (+1/-1), or None if unmeasurable.
        p_alt: Forwarded to ic_sign_e_value_factor.

    Returns:
        The new cumulative e-value. Deterministic given fixed inputs.
    """
    if ic_sign is None:
        return prior_cumulative
    return prior_cumulative * ic_sign_e_value_factor(ic_sign, p_alt)


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
        stride: Subsampling stride used to create X_sub/returns_sub. No longer used
                for window sizing (todo 096) -- kept for call-site compatibility and
                as context for callers/logging. Window size is a fixed subsampled-bar
                target (config.sharpe_window_size_subsampled), so per-window
                statistical power is comparable across every lookahead scale.

    Returns: (sharpe_arr, sharpe_hac_arr, sortino_arr, win_rate_arr, n_windows)
    """
    del stride  # no longer load-bearing for window sizing -- see docstring above
    sharpe_window_size = max(1, config.sharpe_window_size_subsampled)
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


# ---------------------------------------------------------------------------
# Stratified regime-shift guard (todo 144): pure decision, no DB/clock/config.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardVerdict:
    """Verdict for one (tf, regime_group) stratum's fail-fraction this run.

    band_source distinguishes a cold-start decision (seeded rails only, no
    history yet) from a calibrated one (empirical median/MAD band, intersected
    with the rails) -- callers can log/alert differently on "seeded" verdicts
    to signal the guard hasn't self-calibrated yet for that stratum.
    """

    status: Literal["ok", "hold_high", "alert_low", "insufficient_cells"]
    band_lo: float
    band_hi: float
    band_source: Literal["seeded", "empirical"]
    n_history: int


def evaluate_guard_fraction(
    fail_fraction: float,
    n_cells: int,
    history: Sequence[float],
    *,
    min_cells: int,
    min_history: int,
    band_z: float,
    rail_lo: float,
    rail_hi: float,
) -> GuardVerdict:
    """Decide whether one stratum's fail-fraction is ordinary or anomalous.

    Two layers, always intersected so the empirical layer can only TIGHTEN the
    seeded rails, never widen past them (a slowly-drifting baseline cannot
    self-normalize an emerging problem into "ok"):

    1. Seeded rails [rail_lo, rail_hi] -- always active, empirically grounded
       against this corpus's known base rate (not a guess).
    2. Empirical band (median +/- band_z * 1.4826*MAD over `history`) -- only
       once len(history) >= min_history. Falls back to the seeded rails if the
       history is degenerate (MAD == 0), since a zero-width band would flag
       almost any value.

    A stratum with fewer than min_cells active cells is never hold-authoritative
    (status="insufficient_cells") -- its fraction is too noisy (small-N binomial
    variance) to trust either as a hold trigger or as history for other strata.
    """
    if n_cells < min_cells:
        return GuardVerdict(
            status="insufficient_cells",
            band_lo=rail_lo,
            band_hi=rail_hi,
            band_source="seeded",
            n_history=len(history),
        )

    n_history = len(history)
    if n_history >= min_history:
        history_arr = np.asarray(history, dtype=np.float64)
        median = float(np.median(history_arr))
        mad = float(np.median(np.abs(history_arr - median)))
        if mad > 0.0:
            robust_std = 1.4826 * mad
            band_lo = max(median - band_z * robust_std, rail_lo)
            band_hi = min(median + band_z * robust_std, rail_hi)
            band_source: Literal["seeded", "empirical"] = "empirical"
        else:
            # Degenerate history (zero spread) -- fall back to the rails rather
            # than collapse to a single point.
            band_lo, band_hi = rail_lo, rail_hi
            band_source = "seeded"
    else:
        band_lo, band_hi = rail_lo, rail_hi
        band_source = "seeded"

    if fail_fraction > band_hi:
        status: Literal["ok", "hold_high", "alert_low"] = "hold_high"
    elif fail_fraction < band_lo:
        status = "alert_low"
    else:
        status = "ok"

    return GuardVerdict(
        status=status,
        band_lo=band_lo,
        band_hi=band_hi,
        band_source=band_source,
        n_history=n_history,
    )
