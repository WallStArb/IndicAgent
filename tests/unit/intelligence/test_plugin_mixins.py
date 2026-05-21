"""Tests for src/intelligence/plugins/mixins.py.

Covers:
- wilders_update(): normal cases, edge cases (period=1, zero values), NaN propagation,
  negative values, period validation, and numerical stability.
- update_ema(): normal cases, alpha formula correctness, NaN propagation, span
  validation, and numerical stability.
- get_main_df(): valid/insufficient data, missing key, None values, exact min_bars
  boundary, empty DataFrame, and None frames argument.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.intelligence.plugins.mixins import get_main_df, update_ema, wilders_update

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n: int) -> pd.DataFrame:
    """Return a minimal DataFrame with ``n`` rows."""
    return pd.DataFrame({"close": range(n), "open": range(n), "high": range(n), "low": range(n)})


# ---------------------------------------------------------------------------
# TestWildersUpdate
# ---------------------------------------------------------------------------


class TestWildersUpdate:
    def test_normal_case(self):
        """(prev * (period-1) + new_val) / period."""
        result = wilders_update(10.0, 20.0, 14)
        expected = (10.0 * 13 + 20.0) / 14
        assert abs(result - expected) < 1e-10

    def test_period_one(self):
        """period=1 collapses to new_val (weight of prev is 0)."""
        result = wilders_update(10.0, 20.0, 1)
        assert result == pytest.approx(20.0)

    def test_nan_prev_propagates(self):
        """NaN in prev -> NaN out."""
        result = wilders_update(float("nan"), 20.0, 14)
        assert math.isnan(result)

    def test_nan_new_val_propagates(self):
        """NaN in new_val -> NaN out."""
        result = wilders_update(10.0, float("nan"), 14)
        assert math.isnan(result)

    def test_nan_both_propagates(self):
        """NaN in both args -> NaN out."""
        result = wilders_update(float("nan"), float("nan"), 14)
        assert math.isnan(result)

    def test_zero_values(self):
        """Zero inputs produce zero output."""
        result = wilders_update(0.0, 0.0, 14)
        assert result == pytest.approx(0.0)

    def test_negative_values(self):
        """Negative values handled correctly."""
        result = wilders_update(-5.0, -3.0, 14)
        expected = (-5.0 * 13 + (-3.0)) / 14
        assert abs(result - expected) < 1e-10

    def test_period_validation_zero(self):
        """period=0 raises ValueError."""
        with pytest.raises(ValueError):
            wilders_update(1.0, 2.0, 0)

    def test_period_validation_negative(self):
        """period=-1 raises ValueError."""
        with pytest.raises(ValueError):
            wilders_update(1.0, 2.0, -1)

    def test_numerical_stability(self):
        """1000 iterations with constant input converges to that constant."""
        constant = 42.0
        period = 14
        val = 0.0  # start far from constant
        for _ in range(1000):
            val = wilders_update(val, constant, period)
        # After 1000 Wilder's steps with constant input, must converge
        assert abs(val - constant) < 1e-6

    @pytest.mark.parametrize(
        "prev, new_val, period",
        [
            (100.0, 105.0, 7),
            (0.5, 1.5, 5),
            (1000.0, 999.0, 20),
        ],
    )
    def test_formula_parametrized(self, prev, new_val, period):
        """Formula holds across varied inputs."""
        expected = (prev * (period - 1) + new_val) / period
        assert wilders_update(prev, new_val, period) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestUpdateEMA
# ---------------------------------------------------------------------------


class TestUpdateEMA:
    def test_normal_case(self):
        """alpha * current + (1-alpha) * prev_ema, alpha=2/(span+1)."""
        alpha = 2.0 / 21
        expected = alpha * 20.0 + (1 - alpha) * 10.0
        result = update_ema(20.0, 10.0, 20)
        assert result == pytest.approx(expected)

    def test_alpha_formula(self):
        """alpha is exactly 2 / (span + 1)."""
        span = 20
        alpha = 2.0 / (span + 1)
        # When prev_ema == current, result == current regardless of alpha
        assert update_ema(5.0, 5.0, span) == pytest.approx(5.0)
        # Verify alpha indirectly: result = alpha * c + (1-alpha) * p
        result = update_ema(20.0, 10.0, span)
        assert abs(result - (alpha * 20.0 + (1 - alpha) * 10.0)) < 1e-12

    def test_span_one_returns_current(self):
        """span=1 -> alpha=1.0 -> output equals current (no smoothing)."""
        result = update_ema(20.0, 10.0, 1)
        assert result == pytest.approx(20.0)

    def test_nan_current_propagates(self):
        """NaN current -> NaN out."""
        result = update_ema(float("nan"), 10.0, 20)
        assert math.isnan(result)

    def test_nan_prev_ema_propagates(self):
        """NaN prev_ema -> NaN out."""
        result = update_ema(20.0, float("nan"), 20)
        assert math.isnan(result)

    def test_span_validation_zero(self):
        """span=0 raises ValueError."""
        with pytest.raises(ValueError):
            update_ema(1.0, 2.0, 0)

    def test_span_validation_negative(self):
        """span=-5 raises ValueError."""
        with pytest.raises(ValueError):
            update_ema(1.0, 2.0, -5)

    def test_numerical_stability(self):
        """1000 iterations with constant input converges to that constant."""
        constant = 100.0
        span = 12
        val = 0.0
        for _ in range(1000):
            val = update_ema(constant, val, span)
        assert abs(val - constant) < 1e-4

    def test_zero_values(self):
        """Zero current and zero prev_ema produce zero."""
        result = update_ema(0.0, 0.0, 14)
        assert result == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "current, prev_ema, span",
        [
            (50.0, 48.0, 12),
            (1.0, 2.0, 26),
            (0.001, 0.002, 9),
        ],
    )
    def test_formula_parametrized(self, current, prev_ema, span):
        """Formula holds across varied inputs."""
        alpha = 2.0 / (span + 1)
        expected = alpha * current + (1 - alpha) * prev_ema
        assert update_ema(current, prev_ema, span) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestGetMainDf
# ---------------------------------------------------------------------------


class TestGetMainDf:
    def test_valid_dataframe_returns_df(self):
        """Returns df when len(df) >= min_bars."""
        df = _make_df(10)
        result = get_main_df({"main": df}, 5)
        assert result is df

    def test_insufficient_bars_returns_none(self):
        """Returns None when len(df) < min_bars."""
        df = _make_df(4)
        result = get_main_df({"main": df}, 5)
        assert result is None

    def test_missing_main_key_returns_none(self):
        """Returns None when 'main' key is absent from frames."""
        result = get_main_df({"other": _make_df(10)}, 5)
        assert result is None

    def test_none_main_value_returns_none(self):
        """Returns None when frames['main'] is None."""
        result = get_main_df({"main": None}, 5)
        assert result is None

    def test_exact_min_bars_returns_df(self):
        """Returns df when len(df) == min_bars exactly."""
        df = _make_df(5)
        result = get_main_df({"main": df}, 5)
        assert result is df

    def test_empty_dataframe_returns_none(self):
        """Returns None for an empty DataFrame (len 0 < any min_bars >= 1)."""
        df = pd.DataFrame()
        result = get_main_df({"main": df}, 1)
        assert result is None

    def test_none_frames_argument_returns_none(self):
        """Returns None when frames itself is None (not a dict)."""
        result = get_main_df(None, 5)
        assert result is None

    def test_non_dict_frames_returns_none(self):
        """Returns None when frames is not a dict (e.g. a list)."""
        result = get_main_df([1, 2, 3], 5)  # type: ignore[arg-type]
        assert result is None

    def test_empty_dict_returns_none(self):
        """Returns None for an empty dict (no 'main' key)."""
        result = get_main_df({}, 5)
        assert result is None

    def test_non_dataframe_main_returns_none(self):
        """Returns None when frames['main'] is not a DataFrame."""
        result = get_main_df({"main": [1, 2, 3, 4, 5]}, 3)
        assert result is None

    @pytest.mark.parametrize(
        "n_bars,min_bars,should_return",
        [
            (10, 10, True),  # exact boundary
            (9, 10, False),  # one below
            (11, 10, True),  # one above
            (0, 1, False),  # empty
            (1, 1, True),  # single bar
        ],
    )
    def test_boundary_parametrized(self, n_bars, min_bars, should_return):
        """Boundary conditions for len(df) vs min_bars."""
        df = _make_df(n_bars)
        result = get_main_df({"main": df}, min_bars)
        if should_return:
            assert result is df
        else:
            assert result is None
