"""Factor-loading measurement kernel for the Empirical Instrument Tag Calibrator
(Phase 146, TAG-01) -- standardized OLS loading, HAC (Newey-West Bartlett-kernel)
standard error / p-value, the shared long-short factor-series constructor (four
call sites: credit_beta/HYG-IEF, inflation/TIP-IEF, yield_curve/IEF-SHY,
oil_beta/XLE-SPY), and the vol_beta factor-input adapter.

Extends src.intelligence.statistics.ic_math (F4, todo 048/069): every reusable
CI / p-value / FDR / condition-number primitive this module needs is IMPORTED
from ic_math, never reimplemented -- this repo already paid the extraction cost
once when ic_math.py was pulled out of services/ic_engine.py. The only genuinely
new math here is the standardized loading itself, its HAC-adjusted standard
error/p-value, and the long-short spread constructor -- see RESEARCH.md A2/F3
and 146-PATTERNS.md for the design rationale.

Pure functions only -- no DB, no config loading, no module-global mutable state.
Callers (services/tag_calibrator.py, Plan 04) pass hac_max_lag/condition_max as
plain arguments sourced from their own APR-backed config dataclass; this module
does not define or import a config Protocol/dataclass of its own (unlike
ic_math.py's SharpeWindowConfig) because every function here needs at most one
or two scalar tunables, not a multi-field config object -- passing them as
ordinary parameters keeps this module's only dependency the four ic_math
functions listed below plus breadth_vol's causal vol proxy.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from src.intelligence.regime_signals.breadth_vol import _compute_vix_pct_rank
from src.intelligence.statistics.ic_math import (
    _arctanh_clip,
    _circular_shift_null,
    _p_values_from_ic,
    check_condition_number,
)

__all__ = [
    "long_short_daily_returns",
    "standardized_loading",
    "loading_hac_pvalue",
    "spy_realized_vol_factor",
    "partial_loading",
    "partial_loading_ci_low",
    "sign_stable_window_count",
    "partial_loading_null_arm_p",
]


# ---------------------------------------------------------------------------
# Long-short factor-series constructor (shared: HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY)
# ---------------------------------------------------------------------------


def long_short_daily_returns(long_close: np.ndarray, short_close: np.ndarray) -> np.ndarray:
    """Long-short daily log-return spread: log(long[t]/long[t-1]) - log(short[t]/short[t-1]).

    Shared constructor for credit_beta (HYG-IEF), inflation (TIP-IEF), yield_curve
    (IEF-SHY), and oil_beta (XLE-SPY) factor series -- one function, four call
    sites in services/tag_calibrator.py (Plan 04).

    Args:
        long_close: Shape [n_bars] -- long-leg daily close prices.
        short_close: Shape [n_bars] -- short-leg daily close prices, same length
            and calendar alignment as long_close (caller's responsibility --
            see tests/unit/test_spread_leg_pair_validity.py for the pair-symmetry
            data-contract guard).

    Returns:
        Shape [n_bars - 1] -- the spread's daily log-return series.
    """
    long_close = np.asarray(long_close, dtype=np.float64)
    short_close = np.asarray(short_close, dtype=np.float64)
    long_ret = np.diff(np.log(long_close))
    short_ret = np.diff(np.log(short_close))
    return long_ret - short_ret


# ---------------------------------------------------------------------------
# Standardized OLS loading (F3): signed Pearson correlation, bounded [-1, 1]
# ---------------------------------------------------------------------------


def standardized_loading(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    condition_max: float,
) -> float:
    """Standardized OLS loading = signed Pearson correlation of the two return
    series = cov(x, y) / (std(x) * std(y)), bounded [-1, 1].

    This IS the univariate-OLS beta standardized by sigma_factor/sigma_instrument
    (F3 design-doc resolution) -- computed directly as a correlation rather than
    a full statsmodels.OLS solve, since the two are mathematically identical for
    a single regressor (RESEARCH.md A2). Deliberately does NOT pull in
    statsmodels.regression.linear_model.OLS.

    Degenerate guard (T-146-05): a near-constant (zero-variance) instrument or
    factor series cannot produce a meaningful loading -- returns NaN rather than
    a spurious 0.0 or +/-inf. Also runs check_condition_number (reused from
    ic_math, not reimplemented) on the [instrument_ret, factor_ret] matrix as an
    ill-conditioning gate -- catches the same class of degenerate/near-collinear
    input the zero-variance guard is meant to catch, before a spurious loading
    is emitted.

    Args:
        instrument_ret: Shape [n_obs] -- instrument daily return series.
        factor_ret: Shape [n_obs] -- factor daily return series (paired,
            same length and calendar alignment as instrument_ret).
        condition_max: Ill-conditioning threshold forwarded to
            check_condition_number (caller-supplied, e.g. from the service's
            own APR-backed config -- this module has no config of its own).

    Returns:
        loading in [-1, 1], or NaN when n < 2, either series is degenerate
        (near-zero variance), or the condition-number gate fails.
    """
    instrument_ret = np.asarray(instrument_ret, dtype=np.float64)
    factor_ret = np.asarray(factor_ret, dtype=np.float64)
    n = len(instrument_ret)
    if n < 2:
        return float("nan")

    std_x = float(instrument_ret.std())
    std_y = float(factor_ret.std())
    if std_x < 1e-12 or std_y < 1e-12:
        return float("nan")

    matrix = np.column_stack([instrument_ret, factor_ret])
    is_ok, _cond = check_condition_number(matrix, condition_max)
    if not is_ok:
        return float("nan")

    cov = float(
        np.mean((instrument_ret - instrument_ret.mean()) * (factor_ret - factor_ret.mean()))
    )
    loading = cov / (std_x * std_y)
    return float(np.clip(loading, -1.0, 1.0))


def _loading_standard_errors(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    hac_max_lag: int,
) -> tuple[float, float, float, int]:
    """Naive (iid) and HAC (Newey-West Bartlett-kernel) standard errors for the
    standardized loading between two return series.

    The standardized loading r = mean(zx * zy), where zx/zy are the two return
    series z-scored (demeaned, divided by their own std). This per-observation
    product series zx*zy plays exactly the role ic_math._hac_sharpe_nd's
    per-window IC series plays for IC Sharpe: its own autocorrelation structure
    is what the Newey-West correction needs to measure. This function reuses
    _hac_sharpe_nd's gamma_k/rho_k/Bartlett-weight inflation-factor accumulation
    loop pattern (ic_math.py lines ~754-760) -- NOT the function itself (that one
    is Sharpe-specific: mean_ic/hac_std over an [n_windows, n_features] matrix);
    here the same kernel math is applied to a single demeaned scalar series.

    Returns:
        (naive_se, hac_se, r, n):
          naive_se = 1/sqrt(n-3), the Fisher-style asymptotic SE of a
              correlation coefficient (matches ic_math._fisher_z_ci's own se).
          hac_se = naive_se * sqrt(inflation); inflation is floored at 1.0
              (matches _hac_sharpe_nd's own "can't be more precise than i.i.d."
              floor) so hac_se >= naive_se always.
          r = the standardized loading itself (mean of the product series).
          n = paired sample size used.
        All four are NaN/0 when n < 4 (undefined SE) or either input series is
        degenerate (near-zero variance -- no correlation is measurable).
    """
    instrument_ret = np.asarray(instrument_ret, dtype=np.float64)
    factor_ret = np.asarray(factor_ret, dtype=np.float64)
    n = len(instrument_ret)
    if n < 4:
        return float("nan"), float("nan"), float("nan"), n

    std_x = float(instrument_ret.std())
    std_y = float(factor_ret.std())
    if std_x < 1e-12 or std_y < 1e-12:
        return float("nan"), float("nan"), float("nan"), n

    zx = (instrument_ret - instrument_ret.mean()) / std_x
    zy = (factor_ret - factor_ret.mean()) / std_y
    prod = zx * zy
    r = float(prod.mean())

    naive_se = 1.0 / math.sqrt(max(n - 3, 1e-10))

    demeaned = prod - prod.mean()
    var0 = float((demeaned**2).mean())
    inflation = 1.0
    if hac_max_lag > 0 and n >= hac_max_lag + 2 and var0 > 1e-12:
        for k in range(1, hac_max_lag + 1):
            gamma_k = float((demeaned[k:] * demeaned[:-k]).mean())
            rho_k = gamma_k / var0
            inflation += 2.0 * (1.0 - k / (hac_max_lag + 1)) * rho_k
        inflation = max(inflation, 1.0)  # can't be more precise than i.i.d.

    hac_se = naive_se * math.sqrt(inflation)
    return naive_se, hac_se, r, n


def loading_hac_pvalue(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    hac_max_lag: int,
    extra_fitted_params: int = 0,
) -> float:
    """Two-tailed p-value for the standardized loading (signed correlation)
    between instrument_ret and factor_ret, using a HAC (Newey-West
    Bartlett-kernel) inflation-adjusted effective degrees of freedom rather
    than the naive iid df = n - 2.

    Derives an effective df from the ratio (hac_se/naive_se)^2 -- the same
    inflation factor _loading_standard_errors computes -- applied to the base
    df (n - 2, minus extra_fitted_params for any additional parameter already
    fit before this correlation was computed, e.g. the long-short construction's
    implicit extra fitted parameter from differencing two legs), then passes
    that explicit df through to ic_math._p_values_from_ic (reused, not
    reimplemented) rather than hand-rolling a second t-approximation.

    Args:
        instrument_ret: Shape [n_obs] -- instrument daily return series.
        factor_ret: Shape [n_obs] -- factor daily return series (paired).
        hac_max_lag: Bartlett-kernel max lag K forwarded to
            _loading_standard_errors. K=0 disables the HAC correction (naive
            df = n - 2 - extra_fitted_params is used unchanged).
        extra_fitted_params: Additional degrees of freedom to subtract beyond
            the standard n - 2, e.g. for the long-short construction. Defaults
            to 0 (plain single-instrument-vs-single-factor case).

    Returns:
        Two-tailed p-value in [0, 1], or NaN when the standard errors are
        undefined (n < 4 or a degenerate input series -- see
        _loading_standard_errors).
    """
    naive_se, hac_se, r, n = _loading_standard_errors(instrument_ret, factor_ret, hac_max_lag)
    if math.isnan(naive_se) or naive_se < 1e-12:
        return float("nan")

    inflation = (hac_se / naive_se) ** 2
    base_df = max(n - 2 - extra_fitted_params, 1)
    effective_df = max(int(round(base_df / inflation)), 1)
    return float(_p_values_from_ic(np.array([r]), n, df=effective_df)[0])


# ---------------------------------------------------------------------------
# vol_beta factor-input adapter (D-02): reuse breadth_vol's causal proxy verbatim
# ---------------------------------------------------------------------------


def spy_realized_vol_factor(
    spy_close: pd.Series,
    realized_vol_window: int,
    vix_z_window: int,
) -> pd.Series:
    """Thin adapter: vol_beta's factor-series input is breadth_vol's causal
    SPY-realized-vol proxy, reused VERBATIM (D-02, T-146-06) -- never a
    re-derived whole-series percentile rank (Phase 141 P0-T2 look-ahead
    invariant).

    Returns breadth_vol._compute_vix_pct_rank(...) directly; this function
    exists only to give services/tag_calibrator.py (Plan 04) a single,
    obviously-named import target inside factor_math.py's public surface
    rather than importing across two Ring 1 modules from the service. See
    breadth_vol.py's own module docstring for the causal bisect-based
    expanding-rank mechanics this preserves.

    Args:
        spy_close: SPY daily close series, indexed by timestamp, ascending.
        realized_vol_window: Rolling window (bars) for realized-vol computation.
        vix_z_window: Rolling window (bars) for the vol z-score.

    Returns:
        Causal expanding-percentile-rank series, same index as spy_close.
        Leading NaNs during warmup (caller drops them, matching breadth_vol's
        own convention).
    """
    return _compute_vix_pct_rank(spy_close, realized_vol_window, vix_z_window)


# ---------------------------------------------------------------------------
# Pearson partial-loading kernel (Phase 175 Task 1, R-01/R-05/R-06): the
# orthogonalized loading D-01's materiality filter needs -- reuses
# ic_math.partial_spearman_ic's SHAPE (shared-lstsq residualization, the
# check_condition_number ill-conditioning gate, the n < k + 4 floor) on raw
# centered returns rather than rank-transformed values, since this project's
# existing loading/loading_threshold values (Phase 146, TAG-01) are
# Pearson-calibrated, not rank correlations (RESEARCH.md Pitfall 1).
# ---------------------------------------------------------------------------


def _partial_residuals(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
) -> tuple[np.ndarray, np.ndarray, float, int] | None:
    """Shared residualization step for partial_loading/partial_loading_ci_low:
    center instrument_ret, factor_ret, and every control column, gate on
    check_condition_number (reused from ic_math, never reimplemented -- same
    gate mean_variance_weights() and partial_spearman_ic() both use), then
    solve ONE shared least-squares call against controls_centered with
    column_stack([instrument_c, factor_c]) as the right-hand side, and
    residualize both series from the shared coefficient columns -- mirrors
    partial_spearman_ic's structure exactly, minus the rank transform (R-01:
    Pearson, not Spearman).

    Returns (resid_instrument, resid_factor, r2_controls, n), or None on any
    guard failure:
      - n < k + 4 (too few observations for the control count)
      - the centered control design matrix is ill-conditioned (constant
        column, near-collinear controls, etc.)
      - instrument_ret itself is near-constant (sum-of-squares < 1e-12 --
        undefined R2_controls denominator)
      - either residual series is degenerate after removing the controls'
        shared variance (sum-of-squares < 1e-10 -- the same "unmeasurable,
        not a spurious zero" guard partial_spearman_ic applies; this is what
        catches the duplicate-column case, where factor_ret equals one of
        the control legs exactly and its own residual is ~0)
    """
    instrument_ret = np.asarray(instrument_ret, dtype=np.float64)
    factor_ret = np.asarray(factor_ret, dtype=np.float64)
    controls = np.asarray(controls, dtype=np.float64)
    if controls.ndim == 1:
        controls = controls.reshape(-1, 1)
    n = len(instrument_ret)
    k = controls.shape[1]
    if n < k + 4:
        return None

    instrument_c = instrument_ret - instrument_ret.mean()
    factor_c = factor_ret - factor_ret.mean()
    controls_c = controls - controls.mean(axis=0)

    cond_ok, _cond = check_condition_number(controls_c, condition_max)
    if not cond_ok:
        return None

    denom_instrument = float((instrument_c**2).sum())
    if denom_instrument < 1e-12:
        return None

    coefs, _, _, _ = np.linalg.lstsq(
        controls_c, np.column_stack([instrument_c, factor_c]), rcond=None
    )
    resid_instrument = instrument_c - controls_c @ coefs[:, 0]
    resid_factor = factor_c - controls_c @ coefs[:, 1]

    r2_controls = 1.0 - float((resid_instrument**2).sum()) / denom_instrument

    if float((resid_instrument**2).sum()) < 1e-10 or float((resid_factor**2).sum()) < 1e-10:
        return None

    return resid_instrument, resid_factor, r2_controls, n


def partial_loading(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
) -> tuple[float, float, int]:
    """Pearson-convention partial loading of instrument_ret vs factor_ret,
    controlling for one or more control variables (Phase 175 Task 1, R-01).

    NOT a wrapper around ic_math.partial_spearman_ic -- that function is
    rank-based (Spearman); this project's existing loading/loading_threshold
    values (Phase 146, TAG-01 standardized_loading above) are Pearson,
    computed on raw returns, so a rank-based partial_loading sitting in the
    adjacent instrument_tags column would silently compare two different
    statistical conventions (RESEARCH.md Pitfall 1). Only partial_spearman_ic's
    SHAPE is reused (see _partial_residuals) -- the rank transform itself is
    dropped.

    Returns (partial_loading, incremental_r2, n):
      partial_loading: Pearson correlation of the two residual series
        (resid_instrument, resid_factor from _partial_residuals), clipped to
        [-1, 1] -- same np.clip convention as standardized_loading. NaN when
        the shared residualization guard fails.
      incremental_r2: R2_full - R2_controls (R-06) -- the ADDED explanatory
        power of factor_ret over a controls-only regression of instrument_ret.
        Strictly <= the squared partial correlation always, making this the
        stricter reading of a `>= threshold` gate (D-05: seed the more
        conservative interpretation) -- squared partial correlation is
        exactly partial_loading ** 2, information the adjacent column already
        carries, so storing THIS is genuinely new rather than redundant.
        Floored at 0.0 only when the raw value is above -1e-9; anything more
        negative than that is a real numerical failure (not float noise
        around zero) and is returned as NaN rather than silently floored.
      n: input length, always returned even on a NaN result (so callers can
        distinguish "no signal" from "couldn't measure").
    """
    instrument_arr = np.asarray(instrument_ret, dtype=np.float64)
    factor_arr = np.asarray(factor_ret, dtype=np.float64)
    controls_arr = np.asarray(controls, dtype=np.float64)
    if controls_arr.ndim == 1:
        controls_arr = controls_arr.reshape(-1, 1)
    n = len(instrument_arr)

    residuals = _partial_residuals(instrument_arr, factor_arr, controls_arr, condition_max)
    if residuals is None:
        return float("nan"), float("nan"), n
    resid_instrument, resid_factor, r2_controls, n = residuals

    denom = math.sqrt(float((resid_instrument**2).sum()) * float((resid_factor**2).sum()))
    loading = float(np.clip((resid_instrument * resid_factor).sum() / denom, -1.0, 1.0))

    # Second (and last) lstsq call in this module: the full model (controls +
    # factor) regressed against the instrument, to derive R2_full for R-06's
    # incremental-R2 definition. _partial_residuals' single shared lstsq call
    # already solved the controls-only regression for both instrument and
    # factor; this is a genuinely separate design matrix (controls + factor
    # as regressors), not reusable from that call.
    instrument_c = instrument_arr - instrument_arr.mean()
    factor_c = factor_arr - factor_arr.mean()
    controls_c = controls_arr - controls_arr.mean(axis=0)
    full_design = np.column_stack([controls_c, factor_c])

    # _partial_residuals only gates controls_c's OWN condition number -- a
    # candidate factor that is almost (but not quite) a linear combination of
    # the controls can still make this separate, factor-inclusive design
    # matrix severely ill-conditioned even though controls_c alone passed
    # (code review WR-01). Gated the same way as every other linear solve in
    # this module (see check_condition_number's docstring).
    full_cond_ok, _full_cond = check_condition_number(full_design, condition_max)
    if not full_cond_ok:
        return float("nan"), float("nan"), n

    coefs_full, _, _, _ = np.linalg.lstsq(full_design, instrument_c, rcond=None)
    resid_full = instrument_c - full_design @ coefs_full
    denom_instrument = float((instrument_c**2).sum())
    r2_full = 1.0 - float((resid_full**2).sum()) / denom_instrument

    incremental_r2 = r2_full - r2_controls
    if incremental_r2 < -1e-9:
        incremental_r2 = float("nan")
    else:
        incremental_r2 = max(incremental_r2, 0.0)

    return loading, incremental_r2, n


def partial_loading_ci_low(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
    hac_max_lag: int,
    alpha: float,
) -> float:
    """Lower bound of the two-sided (1 - alpha) Fisher-z confidence interval
    on abs(partial_loading) -- Codex's fifth materiality-gate component (R-05).

    Reuses _partial_residuals for the shared orthogonalization step and
    _loading_standard_errors for the HAC (Newey-West) inflation factor -- but
    NOT that function's own returned naive_se directly: _loading_standard_errors'
    1/sqrt(n-3) carries no control-count reduction, which a partial
    correlation's reduced degrees of freedom (n - k - 3) requires. Only the
    inflation RATIO (hac_se/naive_se)**2 is reused; this function derives its
    own control-count-adjusted naive_se from that ratio.

    R-05: alpha is the caller-supplied project-standard
    alpha.tag_calibrator.fdr_alpha (0.05) rather than a new APR key for the
    same two-sided alpha.

    Returns NaN whenever partial_loading itself would return NaN (the shared
    _partial_residuals guard), or when the HAC standard error is undefined
    (naive_se NaN or < 1e-12) or the adjusted degrees of freedom (n - k - 3)
    is non-positive.
    """
    instrument_arr = np.asarray(instrument_ret, dtype=np.float64)
    factor_arr = np.asarray(factor_ret, dtype=np.float64)
    controls_arr = np.asarray(controls, dtype=np.float64)
    if controls_arr.ndim == 1:
        controls_arr = controls_arr.reshape(-1, 1)
    k = controls_arr.shape[1]

    residuals = _partial_residuals(instrument_arr, factor_arr, controls_arr, condition_max)
    if residuals is None:
        return float("nan")
    resid_instrument, resid_factor, _r2_controls, n = residuals

    denom = math.sqrt(float((resid_instrument**2).sum()) * float((resid_factor**2).sum()))
    r = abs(float((resid_instrument * resid_factor).sum() / denom))

    naive_se, hac_se, _r, _n = _loading_standard_errors(resid_instrument, resid_factor, hac_max_lag)
    if math.isnan(naive_se) or naive_se < 1e-12:
        return float("nan")
    inflation = (hac_se / naive_se) ** 2

    dof = n - k - 3
    if dof <= 0:
        return float("nan")
    se = (1.0 / math.sqrt(dof)) * math.sqrt(inflation)

    z_crit = float(norm.ppf(1 - alpha / 2))
    return float(np.tanh(_arctanh_clip(r) - z_crit * se))


# ---------------------------------------------------------------------------
# Sign-stability across disjoint tail-anchored historical windows (Phase 175
# Task 2). No existing analog anywhere in this codebase (RESEARCH.md
# Pitfall 3 / 175-PATTERNS.md "No Analog Found") -- new code, not a wrapper
# around an existing helper.
# ---------------------------------------------------------------------------


def sign_stable_window_count(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
    window_days: int,
    window_count: int,
    full_loading: float | None = None,
) -> tuple[int, int]:
    """Count how many of window_count disjoint, tail-anchored historical
    windows share the full-sample partial_loading's sign.

    full_loading: the caller's already-computed partial_loading() result for
    the identical (instrument_ret, factor_ret, controls, condition_max)
    inputs, when available -- skips a redundant lstsq solve over the full
    sample. Defaults to None, which recomputes it internally (unchanged
    behavior for callers that only have the windowed inputs on hand).

    Resolves the three ambiguities Pitfall 3 names -- recorded here, not
    left implicit:

    Disjoint, tail-anchored: window i (i in range(window_count)) covers the
    slice [n - (i + 1) * window_days : n - i * window_days]. No overlap, no
    stride; window 0 is always the newest observations, window
    window_count - 1 the oldest evaluable segment.

    Short windows are skipped, not padded: once n < (i + 1) * window_days,
    that window and every remaining (older) window is also short, so the
    loop stops there. This makes n_evaluable a self-documenting denominator
    -- a symbol with two years of history can never satisfy a 3-of-4
    requirement because its n_evaluable is 2, not a padded 4.

    NaN windows count toward NEITHER term: a window whose own partial_loading
    is NaN (too few observations for its own k + 4 floor, or its own control
    matrix ill-conditioned within that slice only) is excluded from both
    n_sign_stable and n_evaluable.

    Returns (n_sign_stable, n_evaluable). Returns (0, 0) when the full-sample
    partial_loading is itself NaN -- there is no sign to compare windows
    against. A window loading of exactly 0.0 has sign 0 and therefore never
    matches the full-sample sign (which is always nonzero when the
    full-sample loading is a real number) -- a zero loading is not evidence
    of a stable sign, so it correctly never counts as stable.

    Never logs per-window: this runs inside a per-pair corpus loop (CLAUDE.md
    -- never log per-row inside a loop over the full corpus).
    """
    instrument_arr = np.asarray(instrument_ret, dtype=np.float64)
    factor_arr = np.asarray(factor_ret, dtype=np.float64)
    controls_arr = np.asarray(controls, dtype=np.float64)
    if controls_arr.ndim == 1:
        controls_arr = controls_arr.reshape(-1, 1)
    n = len(instrument_arr)

    if full_loading is None:
        full_loading, _incremental_r2, _n = partial_loading(
            instrument_arr, factor_arr, controls_arr, condition_max
        )
    if math.isnan(full_loading):
        return 0, 0
    full_sign = np.sign(full_loading)

    n_sign_stable = 0
    n_evaluable = 0
    for i in range(window_count):
        if n < (i + 1) * window_days:
            break
        start = n - (i + 1) * window_days
        end = n - i * window_days
        window_loading, _, _ = partial_loading(
            instrument_arr[start:end],
            factor_arr[start:end],
            controls_arr[start:end],
            condition_max,
        )
        if math.isnan(window_loading):
            continue
        n_evaluable += 1
        if np.sign(window_loading) == full_sign:
            n_sign_stable += 1

    return n_sign_stable, n_evaluable


# ---------------------------------------------------------------------------
# Circular-shift null arm (Phase 175 Task 3, D-06): shift the factor_series
# proxy's OWN return series -- never the candidate instrument's return, never
# a symbol shuffle.
# ---------------------------------------------------------------------------


def partial_loading_null_arm_p(
    instrument_ret: np.ndarray,
    factor_ret: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
    n_draws: int,
    rng: np.random.Generator,
) -> float:
    """D-06 null-arm p-value: circularly shift ONLY the factor_series proxy's
    own return series, recompute the partial loading against each shifted
    draw, and derive a two-sided p-value.

    D-06 contract: the shift target is the factor proxy's own return series
    -- never the candidate instrument's return (would contaminate the
    market-beta control this filter exists to preserve) and never a
    symbol-shuffle (tests the wrong null: "distinguishable from a random
    other symbol"). The control columns are never shifted either.

    Mechanics source: scripts/analysis/tsmom_per_symbol_ic_screen.py (the
    `p = (1 + sum(null >= observed)) / (N + 1)` construction and the
    `len(null_draws) < 0.5 * _N_NULL` reliability floor) -- reused for shape
    only. That script's own call site shifts the CANDIDATE's return series,
    which is the WRONG target to copy here; D-06 requires the factor proxy.

    Precomputes the control-matrix pseudo-inverse and the candidate's own
    residual ONCE, outside the draw loop -- resid_instrument is invariant
    under any shift of the factor, so this reduces the whole null arm to one
    np.linalg.pinv plus n_draws cheap matmuls rather than n_draws separate
    lstsq solves. This is what keeps the null arm affordable to run inline
    across the whole corpus (see plan 03's R-02).

    Returns NaN without drawing when the observed partial_loading is itself
    NaN (reuses partial_loading for the observed statistic), or when the
    candidate's own residual is degenerate (sum-of-squares below 1e-10) or
    the control design matrix is ill-conditioned. Returns NaN (without a
    usable p-value) when fewer than half of n_draws produce a finite null
    statistic, matching tsmom_per_symbol_ic_screen.py's own reliability
    floor. The comparison is two-sided: abs(null_draw) >= abs(observed).
    """
    instrument_arr = np.asarray(instrument_ret, dtype=np.float64)
    factor_arr = np.asarray(factor_ret, dtype=np.float64)
    controls_arr = np.asarray(controls, dtype=np.float64)
    if controls_arr.ndim == 1:
        controls_arr = controls_arr.reshape(-1, 1)

    observed_loading, _incremental_r2, _n = partial_loading(
        instrument_arr, factor_arr, controls_arr, condition_max
    )
    if math.isnan(observed_loading):
        return float("nan")
    observed = abs(observed_loading)

    # No separate check_condition_number gate here: partial_loading() above
    # already ran it (via _partial_residuals) against this same mean-centered
    # controls_c/condition_max and would have returned NaN by now on failure
    # -- a second call would be unreachable-as-failing dead code.
    controls_c = controls_arr - controls_arr.mean(axis=0)
    instrument_c = instrument_arr - instrument_arr.mean()
    pinv_controls = np.linalg.pinv(controls_c)
    resid_instrument = instrument_c - controls_c @ (pinv_controls @ instrument_c)
    denom_instrument = float((resid_instrument**2).sum())
    if denom_instrument < 1e-10:
        return float("nan")

    draws: list[float] = []
    for _ in range(n_draws):
        shifted = _circular_shift_null(factor_arr, rng)
        shifted_c = shifted - shifted.mean()
        resid_factor = shifted_c - controls_c @ (pinv_controls @ shifted_c)
        denom_factor = float((resid_factor**2).sum())
        if denom_factor < 1e-10:
            continue
        stat = float(
            (resid_instrument * resid_factor).sum() / math.sqrt(denom_instrument * denom_factor)
        )
        if math.isfinite(stat):
            draws.append(stat)

    if len(draws) < 0.5 * n_draws:
        return float("nan")

    finite = np.array(draws)
    p = (1 + int((np.abs(finite) >= observed).sum())) / (len(finite) + 1)
    return float(p)
