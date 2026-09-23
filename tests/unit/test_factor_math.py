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

import src.intelligence.statistics.factor_math as factor_math  # noqa: E402
from src.intelligence.statistics.factor_math import (  # noqa: E402
    _loading_standard_errors,
    loading_hac_pvalue,
    long_short_daily_returns,
    partial_loading,
    partial_loading_ci_low,
    partial_loading_null_arm_p,
    sign_stable_window_count,
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


# ---------------------------------------------------------------------------
# Task 1: Pearson partial-loading kernel (partial_loading / partial_loading_ci_low)
# ---------------------------------------------------------------------------


def test_partial_loading_known_value():
    """y_candidate = 0.6*x_factor + noise, controls independent of both -- the
    orthogonalized partial loading should recover the true 0.6 residual
    correlation (an independent control leaves the raw relationship intact),
    with incremental_r2 > 0 and n equal to the input length."""
    rng = np.random.default_rng(42)
    n = 2000
    true_r = 0.6
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)  # independent of both instrument and factor
    noise = rng.normal(size=n)
    y_candidate = true_r * x_factor + math.sqrt(1 - true_r**2) * noise

    loading, incremental_r2, n_out = partial_loading(
        y_candidate, x_factor, control, condition_max=1e8
    )

    assert abs(loading - true_r) < 0.05, f"Expected partial loading near {true_r}, got {loading}"
    assert incremental_r2 > 0
    assert n_out == n


def test_partial_loading_duplicate_factor_column_returns_nan():
    """x_factor an exact duplicate of the sole control leg: the factor's own
    residual against the controls is exactly zero -- degenerate, never a
    spurious value."""
    rng = np.random.default_rng(43)
    n = 200
    control_leg = rng.normal(size=n)
    controls = control_leg.reshape(-1, 1)
    x_factor_dup = control_leg.copy()
    noise = rng.normal(size=n)
    y_candidate = 0.5 * control_leg + noise

    loading, incremental_r2, n_out = partial_loading(
        y_candidate, x_factor_dup, controls, condition_max=1e8
    )

    assert math.isnan(loading)
    assert math.isnan(incremental_r2)
    assert n_out == n


def test_partial_loading_constant_control_column_returns_nan():
    """A constant (zero-variance) control column ill-conditions the shared
    design matrix -- check_condition_number gate must fail, never a spurious
    result."""
    rng = np.random.default_rng(44)
    n = 200
    x_factor = rng.normal(size=n)
    controls = np.column_stack([rng.normal(size=n), np.ones(n)])
    noise = rng.normal(size=n)
    y_candidate = 0.5 * x_factor + noise

    loading, incremental_r2, n_out = partial_loading(
        y_candidate, x_factor, controls, condition_max=1e8
    )

    assert math.isnan(loading)
    assert math.isnan(incremental_r2)
    assert n_out == n


def test_partial_loading_insufficient_observations_returns_nan():
    """n < k + 4 (fewer observations than controls plus four) must return NaN
    without attempting the solve."""
    rng = np.random.default_rng(45)
    n = 3  # one control -> k=1, need n >= 5
    x_factor = rng.normal(size=n)
    controls = rng.normal(size=n).reshape(-1, 1)
    y_candidate = rng.normal(size=n)

    loading, incremental_r2, n_out = partial_loading(
        y_candidate, x_factor, controls, condition_max=1e8
    )

    assert math.isnan(loading)
    assert math.isnan(incremental_r2)
    assert n_out == n


def test_partial_loading_pure_noise_small_magnitude():
    """y_candidate independent of x_factor after controls: abs(partial_loading)
    and incremental_r2 both small on a seeded 1000-observation draw."""
    rng = np.random.default_rng(46)
    n = 1000
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    y_candidate = rng.normal(size=n)  # independent of x_factor and control

    loading, incremental_r2, n_out = partial_loading(
        y_candidate, x_factor, control, condition_max=1e8
    )

    assert abs(loading) < 0.15, f"Expected small loading under independence, got {loading}"
    assert (
        incremental_r2 < 0.02
    ), f"Expected small incremental_r2 under independence, got {incremental_r2}"
    assert n_out == n


def test_partial_loading_incremental_r2_never_meaningfully_negative():
    """incremental_r2 = R2_full - R2_controls is always >= 0 up to float
    tolerance (never negative beyond -1e-9) across multiple synthetic cases."""
    rng = np.random.default_rng(47)
    n = 1000
    for true_r in (0.0, 0.3, 0.6, -0.6):
        x_factor = rng.normal(size=n)
        control = rng.normal(size=n)
        noise = rng.normal(size=n)
        y_candidate = true_r * x_factor + math.sqrt(1 - true_r**2) * noise
        _loading, incremental_r2, _n = partial_loading(
            y_candidate, x_factor, control, condition_max=1e8
        )
        assert not math.isnan(incremental_r2)
        assert incremental_r2 >= -1e-9


def test_partial_loading_ci_low_strong_relationship_bounded_below_magnitude():
    """On the strong-relationship case, the lower CI bound is strictly less
    than abs(partial_loading) and strictly greater than 0."""
    rng = np.random.default_rng(48)
    n = 2000
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    y_candidate = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    loading, _incremental_r2, _n = partial_loading(
        y_candidate, x_factor, control, condition_max=1e8
    )
    ci_low = partial_loading_ci_low(
        y_candidate, x_factor, control, condition_max=1e8, hac_max_lag=5, alpha=0.05
    )

    assert 0.0 < ci_low < abs(loading)


def test_partial_loading_ci_low_pure_noise_rejects_relationship():
    """On the pure-noise case, the lower CI bound falls below the 0.20 seeded
    gate -- the CI gate rejects a non-relationship."""
    rng = np.random.default_rng(49)
    n = 1000
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    y_candidate = rng.normal(size=n)

    ci_low = partial_loading_ci_low(
        y_candidate, x_factor, control, condition_max=1e8, hac_max_lag=5, alpha=0.05
    )

    assert ci_low < 0.20, f"Expected the CI gate to reject a non-relationship, got {ci_low}"


def test_partial_loading_ci_low_nan_when_partial_loading_nan():
    """partial_loading_ci_low returns NaN whenever partial_loading itself
    returns NaN (the same guard failure, e.g. a constant control column)."""
    rng = np.random.default_rng(50)
    n = 200
    x_factor = rng.normal(size=n)
    controls = np.column_stack([rng.normal(size=n), np.ones(n)])
    y_candidate = rng.normal(size=n)

    loading, _incremental_r2, _n = partial_loading(
        y_candidate, x_factor, controls, condition_max=1e8
    )
    ci_low = partial_loading_ci_low(
        y_candidate, x_factor, controls, condition_max=1e8, hac_max_lag=5, alpha=0.05
    )

    assert math.isnan(loading)
    assert math.isnan(ci_low)


# ---------------------------------------------------------------------------
# Task 2: sign-stability across disjoint tail-anchored historical windows
# ---------------------------------------------------------------------------


def test_sign_stable_window_count_all_windows_stable():
    """A relationship holding with the same sign across all of history: 4
    disjoint 100-obs windows fitting exactly into 400 observations all match
    the full-sample sign."""
    rng = np.random.default_rng(11)
    n = 400
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    y_candidate = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    result = sign_stable_window_count(
        y_candidate, x_factor, control, condition_max=1e8, window_days=100, window_count=4
    )
    assert result == (4, 4)


def test_sign_stable_window_count_recent_window_flipped():
    """The relationship's sign flips only in the most recent (newest, window
    0) segment: n_sign_stable < n_evaluable, specifically (3, 4)."""
    rng = np.random.default_rng(12)
    n = 400
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    coef = np.where(np.arange(n) < 300, 0.6, -0.6)  # last 100 obs flipped
    y_candidate = coef * x_factor + math.sqrt(1 - 0.36) * noise

    result = sign_stable_window_count(
        y_candidate, x_factor, control, condition_max=1e8, window_days=100, window_count=4
    )
    assert result == (3, 4)


def test_sign_stable_window_count_oldest_window_flipped_proves_tail_anchoring():
    """The relationship's sign flips only in the OLDEST segment (window
    window_count - 1): also (3, 4), but only if windows are correctly
    anchored at the most recent observation -- proves window ordering, not
    just flip-counting."""
    rng = np.random.default_rng(13)
    n = 400
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    coef = np.where(np.arange(n) < 100, -0.6, 0.6)  # oldest 100 obs flipped
    y_candidate = coef * x_factor + math.sqrt(1 - 0.36) * noise

    result = sign_stable_window_count(
        y_candidate, x_factor, control, condition_max=1e8, window_days=100, window_count=4
    )
    assert result == (3, 4)


def test_sign_stable_window_count_short_history_not_padded():
    """250 observations with window_days=100, window_count=4: only 2 full
    windows fit -- n_evaluable must be 2, never a padded 4."""
    rng = np.random.default_rng(14)
    n = 250
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    y_candidate = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    n_stable, n_evaluable = sign_stable_window_count(
        y_candidate, x_factor, control, condition_max=1e8, window_days=100, window_count=4
    )
    assert n_evaluable == 2, f"Expected only 2 full windows to fit in 250 obs, got {n_evaluable}"
    assert n_stable == 2


def test_sign_stable_window_count_nan_window_excluded_from_both_terms():
    """A window whose own partial_loading is NaN (ill-conditioned within that
    window only) is excluded from BOTH n_sign_stable and n_evaluable."""
    rng = np.random.default_rng(15)
    n = 400
    x_factor = rng.normal(size=n)
    noise = rng.normal(size=n)
    control = rng.normal(size=n)
    control[100:200] = 5.0  # constant sub-slice -> ill-conditioned within that window only
    y_candidate = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    n_stable, n_evaluable = sign_stable_window_count(
        y_candidate, x_factor, control, condition_max=1e8, window_days=100, window_count=4
    )
    assert n_evaluable == 3, f"Expected the constant-control window excluded, got {n_evaluable}"
    assert n_stable == 3


def test_sign_stable_window_count_full_sample_nan_returns_zero_zero():
    """When the full-sample partial_loading is itself NaN (e.g. a constant
    control column), returns (0, 0) -- no sign to compare windows against."""
    rng = np.random.default_rng(16)
    n = 400
    x_factor = rng.normal(size=n)
    y_candidate = rng.normal(size=n)
    controls = np.column_stack([rng.normal(size=n), np.ones(n)])

    result = sign_stable_window_count(
        y_candidate, x_factor, controls, condition_max=1e8, window_days=100, window_count=4
    )
    assert result == (0, 0)


# ---------------------------------------------------------------------------
# Task 3: circular-shift null arm (D-06) -- shifts the factor proxy only
# ---------------------------------------------------------------------------


def test_partial_loading_null_arm_p_detects_real_relationship():
    """A candidate genuinely loading on the factor after controls: a small
    p-value on a seeded n_draws=200 run."""
    rng = np.random.default_rng(55)
    n = 500
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    instrument = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    draw_rng = np.random.default_rng(123)
    p = partial_loading_null_arm_p(
        instrument, x_factor, control, condition_max=1e8, n_draws=200, rng=draw_rng
    )
    assert p < 0.05, f"Expected a small p-value for a genuine relationship, got {p}"


def test_partial_loading_null_arm_p_two_sided_detects_negative_relationship():
    """A genuinely NEGATIVE relationship after controls also clears the
    null-arm gate -- proves the comparison is two-sided, not one-sided."""
    rng = np.random.default_rng(555)
    n = 500
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    instrument = -0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    draw_rng = np.random.default_rng(556)
    p = partial_loading_null_arm_p(
        instrument, x_factor, control, condition_max=1e8, n_draws=200, rng=draw_rng
    )
    assert p < 0.05, f"Expected a small p-value for a negative relationship, got {p}"


def test_partial_loading_null_arm_p_rejects_independent_case():
    """A candidate independent of the factor after controls: a large p-value."""
    rng = np.random.default_rng(66)
    n = 500
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    instrument = rng.normal(size=n)  # independent of x_factor and control

    draw_rng = np.random.default_rng(321)
    p = partial_loading_null_arm_p(
        instrument, x_factor, control, condition_max=1e8, n_draws=200, rng=draw_rng
    )
    assert p > 0.20, f"Expected a large p-value for an independent case, got {p}"


def test_partial_loading_null_arm_p_shifts_only_factor_series(monkeypatch):
    """The function shifts ONLY the factor series -- never the candidate's
    own return series, never a control column (D-06)."""
    real_shift = factor_math._circular_shift_null
    recorded = []

    def _recording_shift(y, rng):
        recorded.append(np.array(y, copy=True))
        return real_shift(y, rng)

    monkeypatch.setattr(factor_math, "_circular_shift_null", _recording_shift)

    rng = np.random.default_rng(99)
    n = 300
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    instrument = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    factor_math.partial_loading_null_arm_p(
        instrument, x_factor, control, condition_max=1e8, n_draws=20, rng=np.random.default_rng(7)
    )

    assert len(recorded) == 20
    for shifted_input in recorded:
        np.testing.assert_array_equal(shifted_input, x_factor)
        assert not np.array_equal(shifted_input, instrument)
        assert not np.array_equal(shifted_input, control)


def test_partial_loading_null_arm_p_deterministic_under_seeded_rng():
    """Calling twice with two freshly-seeded generators of the same seed
    returns identical p-values."""
    rng = np.random.default_rng(77)
    n = 400
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    instrument = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    p1 = partial_loading_null_arm_p(
        instrument,
        x_factor,
        control,
        condition_max=1e8,
        n_draws=100,
        rng=np.random.default_rng(999),
    )
    p2 = partial_loading_null_arm_p(
        instrument,
        x_factor,
        control,
        condition_max=1e8,
        n_draws=100,
        rng=np.random.default_rng(999),
    )
    assert p1 == p2


def test_partial_loading_null_arm_p_nan_when_observed_nan():
    """When the observed partial_loading is NaN (n < k + 4 here), returns NaN
    without drawing."""
    rng = np.random.default_rng(1)
    n = 10
    instrument = rng.normal(size=n)
    factor = rng.normal(size=n)
    controls = rng.normal(size=(n, 8))  # k=8, n < k + 4

    p = partial_loading_null_arm_p(
        instrument, factor, controls, condition_max=1e8, n_draws=50, rng=np.random.default_rng(2)
    )
    assert math.isnan(p)


def test_partial_loading_null_arm_p_nan_when_insufficient_finite_draws(monkeypatch):
    """When fewer than half of n_draws produce a finite null statistic,
    returns NaN (matching tsmom_per_symbol_ic_screen.py's reliability floor)."""
    rng = np.random.default_rng(88)
    n = 300
    x_factor = rng.normal(size=n)
    control = rng.normal(size=n)
    noise = rng.normal(size=n)
    instrument = 0.6 * x_factor + math.sqrt(1 - 0.36) * noise

    def _degenerate_shift(y, rng):
        return np.zeros_like(y)

    monkeypatch.setattr(factor_math, "_circular_shift_null", _degenerate_shift)

    p = factor_math.partial_loading_null_arm_p(
        instrument, x_factor, control, condition_max=1e8, n_draws=50, rng=np.random.default_rng(3)
    )
    assert math.isnan(p)
