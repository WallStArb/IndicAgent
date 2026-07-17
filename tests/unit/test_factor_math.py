"""Unit tests: factor_math.py synthetic-fixture correctness (Phase 146, TAG-01).

Pins the standardized loading, HAC standard-error inflation, the shared
long-short constructor, and the causal-rank invariant of the vol_beta factor
adapter. No DB, no network -- pure numpy/pandas synthetic fixtures, CI-clean
(mirrors tests/unit/test_ensemble_ic_math.py's synthetic-fixture style).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.factor_math import (
    _loading_standard_errors,
    loading_hac_pvalue,
    long_short_daily_returns,
    spy_realized_vol_factor,
    standardized_loading,
)


def test_ols_loading_synthetic():
    """Known true correlation recovered within tolerance, correct sign,
    degenerate zero-variance handled."""
    rng = np.random.default_rng(42)
    n = 2000
    true_r = 0.6
    x = rng.normal(size=n)
    y = true_r * x + math.sqrt(1 - true_r**2) * rng.normal(size=n)

    loading = standardized_loading(x, y, condition_max=1e8)
    assert abs(loading - true_r) < 0.05, f"Expected loading near {true_r}, got {loading}"
    assert loading > 0

    # Sign correctness: negative correlation.
    y_neg = -x + rng.normal(scale=0.1, size=n)
    loading_neg = standardized_loading(x, y_neg, condition_max=1e8)
    assert loading_neg < 0, f"Expected negative loading, got {loading_neg}"

    # Degenerate zero-variance guard: a constant series has no measurable loading.
    constant = np.ones(n)
    assert math.isnan(standardized_loading(x, constant, condition_max=1e8))

    # Bounded [-1, 1] even for a near-perfect (but not exactly 1.0) correlation.
    y_perfect = x + rng.normal(scale=1e-6, size=n)
    loading_perfect = standardized_loading(x, y_perfect, condition_max=1e8)
    assert -1.0 <= loading_perfect <= 1.0
    assert loading_perfect > 0.99


def test_hac_se_inflation():
    """On autocorrelated synthetic residuals, the HAC standard error is
    strictly larger than the naive (iid) standard error -- the Newey-West
    inflation is applied."""
    rng = np.random.default_rng(7)
    n = 1000
    phi = 0.9
    x = np.zeros(n)
    innovations = rng.normal(size=n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + innovations[t]
    # Weak signal (small coefficient) so the resulting correlation is modest --
    # a strong correlation at n=1000 drives both naive and HAC p-values to
    # float64 underflow (0.0), making the "HAC p-value is less significant"
    # comparison untestable. A modest, still genuinely nonzero correlation keeps
    # both p-values representable and comparable.
    y = 0.05 * x + rng.normal(scale=1.0, size=n)

    naive_se, hac_se, r, used_n = _loading_standard_errors(x, y, hac_max_lag=15)

    assert used_n == n
    assert not math.isnan(naive_se)
    assert not math.isnan(hac_se)
    assert hac_se > naive_se, (
        f"Expected HAC SE ({hac_se}) to strictly exceed naive SE ({naive_se}) "
        "under strong AR(1) autocorrelation"
    )

    # HAC max_lag=0 disables the correction -- must reproduce the naive SE exactly.
    naive_se_0, hac_se_0, _, _ = _loading_standard_errors(x, y, hac_max_lag=0)
    assert abs(hac_se_0 - naive_se_0) < 1e-12

    # The HAC-adjusted p-value must be less significant (larger) than the naive one
    # for the same autocorrelated data -- larger SE means less confidence.
    p_naive = loading_hac_pvalue(x, y, hac_max_lag=0)
    p_hac = loading_hac_pvalue(x, y, hac_max_lag=15)
    assert p_hac > p_naive, f"Expected HAC p-value ({p_hac}) > naive p-value ({p_naive})"
    assert 0.0 <= p_hac <= 1.0
    assert 0.0 <= p_naive <= 1.0


def test_long_short_constructor():
    """Long-short spread equals element-wise log-return(long) - log-return(short),
    length N-1."""
    long_close = np.array([100.0, 101.0, 102.5, 101.0, 103.0])
    short_close = np.array([50.0, 50.5, 50.0, 49.5, 50.2])

    spread = long_short_daily_returns(long_close, short_close)
    expected = np.diff(np.log(long_close)) - np.diff(np.log(short_close))

    assert spread.shape == (4,)
    np.testing.assert_allclose(spread, expected)


def test_spy_realized_vol_factor_is_causal():
    """Appending a future bar must not alter earlier computed values -- the
    causal-rank invariant (Phase 141 P0-T2) is preserved, not a whole-series
    rank."""
    rng = np.random.default_rng(3)
    n = 400
    prices = 100 + np.cumsum(rng.normal(scale=0.5, size=n))
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    spy_close = pd.Series(prices, index=idx)

    result_full = spy_realized_vol_factor(spy_close, realized_vol_window=20, vix_z_window=100)

    extra_price = prices[-1] + float(rng.normal(scale=0.5))
    idx_extended = pd.date_range("2020-01-01", periods=n + 1, freq="D")
    spy_close_extended = pd.Series(np.append(prices, extra_price), index=idx_extended)
    result_extended = spy_realized_vol_factor(
        spy_close_extended, realized_vol_window=20, vix_z_window=100
    )

    prior = result_full.dropna().to_numpy()
    prior_extended = result_extended.iloc[: len(result_full)].dropna().to_numpy()

    assert len(prior) == len(prior_extended)
    np.testing.assert_allclose(prior, prior_extended)
