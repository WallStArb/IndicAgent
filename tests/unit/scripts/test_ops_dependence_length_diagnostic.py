"""Unit tests for scripts/ops/alpha/ops_dependence_length_diagnostic.py (todo 145).

Pure-function tests only: the 1/e decorrelation-lag proxy for integrated
autocorrelation time, the dependence-length ratio, and the integrity_monitor
INSERT SQL shape. No DB, no asyncio -- mirrors tests/unit/test_forward_return_writer.py's
SQL-structure-test convention.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.ops.alpha.ops_dependence_length_diagnostic import (
    _INSERT_SQL,
    _decorrelation_lag_1_over_e,
    _dependence_length_ratio,
)


def _make_ar1(phi: float, n: int, seed: int = 42) -> np.ndarray:
    """Synthetic AR(1) series: x_t = phi * x_{t-1} + eps_t, eps_t ~ N(0, 1).

    Theoretical ACF is phi**k, so the theoretical 1/e decorrelation lag is
    -1 / ln(phi) for 0 < phi < 1.
    """
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, 1.0, n)
    x = np.empty(n)
    x[0] = eps[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + eps[t]
    return x


class TestDecorrelationLag:
    def test_ar1_lag_matches_theoretical_decay_within_tolerance(self):
        """phi=0.9 -> theoretical decorrelation lag = -1/ln(0.9) ~= 9.49 bars. A
        long, low-noise series should recover this within a small tolerance --
        this is a cheap proxy (todo 145: "sufficient for a flag, not a
        publication-grade estimate"), not an exact estimator."""
        phi = 0.9
        theoretical_lag = -1.0 / np.log(phi)
        series = _make_ar1(phi, n=50_000, seed=7)

        lag = _decorrelation_lag_1_over_e(series)

        assert (
            abs(lag - theoretical_lag) <= 3
        ), f"expected lag near {theoretical_lag:.2f}, got {lag}"

    def test_white_noise_decorrelates_almost_immediately(self):
        """phi=0 (pure white noise) has zero true autocorrelation at every lag >= 1
        -- the empirical 1/e lag should be tiny."""
        series = _make_ar1(0.0, n=5_000, seed=1)

        lag = _decorrelation_lag_1_over_e(series)

        assert lag <= 5

    def test_returns_max_lag_floor_when_dependence_exceeds_search_window(self):
        """A near-unit-root series (phi=0.9999) barely decays at all within a small
        max_lag window -- the function must return max_lag itself as a floor
        estimate (dependence is AT LEAST this long), not silently under-report."""
        series = _make_ar1(0.9999, n=500, seed=3)

        lag = _decorrelation_lag_1_over_e(series, max_lag=50)

        assert lag == 50

    def test_degenerate_short_series_returns_zero(self):
        assert _decorrelation_lag_1_over_e(np.array([1.0, 2.0, 3.0])) == 0

    def test_constant_series_returns_zero(self):
        assert _decorrelation_lag_1_over_e(np.full(1000, 5.0)) == 0

    def test_nan_values_are_dropped_before_computing(self):
        """feature_vectors columns can contain NaN (warmup rows) -- these must be
        filtered, not propagate into the FFT and corrupt every downstream lag."""
        series = _make_ar1(0.9, n=50_000, seed=7)
        series_with_nans = series.copy()
        series_with_nans[::100] = np.nan

        lag_clean = _decorrelation_lag_1_over_e(series)
        lag_with_nans = _decorrelation_lag_1_over_e(series_with_nans)

        assert abs(lag_clean - lag_with_nans) <= 2


class TestDependenceLengthRatio:
    def test_basic_division(self):
        assert _dependence_length_ratio(300.0, 78) == pytest.approx(300.0 / 78.0)

    def test_ratio_above_one_for_long_dependence(self):
        # ctf_momentum-shaped example from the todo: ~150 bar lag vs. 78 bar block.
        assert _dependence_length_ratio(150.0, 78) > 1.0

    def test_zero_or_negative_block_size_returns_nan(self):
        assert np.isnan(_dependence_length_ratio(100.0, 0))
        assert np.isnan(_dependence_length_ratio(100.0, -5))


class TestIntegrityMonitorInsertSqlShape:
    def test_targets_integrity_monitor_table(self):
        assert "INSERT INTO integrity_monitor" in _INSERT_SQL

    def test_monitor_type_is_ic_bootstrap(self):
        assert "'ic_bootstrap'" in _INSERT_SQL

    def test_metric_name_is_dependence_length_ratio(self):
        assert "'dependence_length_ratio'" in _INSERT_SQL

    def test_has_five_positional_params(self):
        for i in range(1, 6):
            assert f"${i}" in _INSERT_SQL

    def test_on_conflict_matches_idempotency_index(self):
        assert (
            "ON CONFLICT (monitor_type, training_window_end, metric_name, "
            "COALESCE(subject, '')" in _INSERT_SQL
        )
