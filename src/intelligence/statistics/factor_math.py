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

from src.intelligence.regime_signals.breadth_vol import _compute_vix_pct_rank
from src.intelligence.statistics.ic_math import (
    _p_values_from_ic,
    check_condition_number,
)

__all__ = [
    "long_short_daily_returns",
    "standardized_loading",
    "loading_hac_pvalue",
    "spy_realized_vol_factor",
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
