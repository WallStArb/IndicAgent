"""Tests for ShannonEntropyPlugin (QUAL-08) — I4 context plugin."""

import numpy as np
import pandas as pd
import pytest


class TestShannonEntropyPluginMetadata:
    @pytest.mark.unit
    def test_plugin_name(self):
        """ShannonEntropyPlugin.name == 'ctx_ShannonEntropy'."""
        from src.intelligence.context.shannon_entropy import plugin

        assert plugin.name == "ctx_ShannonEntropy"

    @pytest.mark.unit
    def test_plugin_outputs(self):
        """ShannonEntropyPlugin.outputs == frozenset({'shannon_entropy', 'entropy_quality'})."""
        from src.intelligence.context.shannon_entropy import plugin

        assert plugin.outputs == frozenset({"shannon_entropy", "entropy_quality"})


def _make_frames(close_arr: np.ndarray) -> dict:
    """Build a frames dict with a 'main' DataFrame for the plugin."""
    df = pd.DataFrame({"close": close_arr})
    return {"main": df}


class TestShannonEntropyComputeFull:
    @pytest.mark.unit
    def test_too_few_bars_returns_empty(self):
        """compute_full() with < 10 bars returns {}."""
        from src.intelligence.context.shannon_entropy import plugin

        frames = _make_frames(np.array([100.0, 101.0, 102.0, 103.0]))
        result = plugin.compute_full(frames)
        assert result == {}

    @pytest.mark.unit
    def test_none_main_returns_empty(self):
        """compute_full() with missing 'main' key returns {}."""
        from src.intelligence.context.shannon_entropy import plugin

        result = plugin.compute_full({})
        assert result == {}

    @pytest.mark.unit
    def test_structured_series_returns_low_entropy(self):
        """Constant price (zero variance) returns shannon_entropy close to 0.0."""
        from src.intelligence.context.shannon_entropy import plugin

        # Flat prices → all log-returns = 0 → single bin occupied → near-zero entropy
        close = np.full(50, 100.0)
        result = plugin.compute_full(_make_frames(close))
        assert "shannon_entropy" in result
        assert (
            result["shannon_entropy"] < 0.3
        ), f"Expected low entropy for flat price series, got {result['shannon_entropy']}"

    @pytest.mark.unit
    def test_chaotic_series_returns_high_entropy(self):
        """Maximally varied return series returns shannon_entropy close to 1.0."""
        from src.intelligence.context.shannon_entropy import plugin

        # Create returns that spread uniformly across all bins → high entropy
        rng = np.random.default_rng(42)
        # Generate log returns that span a wide range uniformly
        log_returns = np.linspace(-0.05, 0.05, 100)
        rng.shuffle(log_returns)
        # Convert to prices
        close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(log_returns)]))
        result = plugin.compute_full(_make_frames(close))
        assert "shannon_entropy" in result
        assert (
            result["shannon_entropy"] > 0.7
        ), f"Expected high entropy for uniform spread series, got {result['shannon_entropy']}"

    @pytest.mark.unit
    def test_entropy_output_in_unit_range(self):
        """shannon_entropy is always in [0, 1]."""
        from src.intelligence.context.shannon_entropy import plugin

        rng = np.random.default_rng(99)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, 50)))
        result = plugin.compute_full(_make_frames(close))
        assert "shannon_entropy" in result
        assert 0.0 <= result["shannon_entropy"] <= 1.0

    @pytest.mark.unit
    def test_entropy_quality_in_result(self):
        """compute_full() also returns 'entropy_quality' key."""
        from src.intelligence.context.shannon_entropy import plugin

        rng = np.random.default_rng(7)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.001, 30)))
        result = plugin.compute_full(_make_frames(close))
        assert "entropy_quality" in result


class TestEntropyQualityFunction:
    @pytest.mark.unit
    def test_low_entropy_returns_1_0(self):
        """entropy_quality(0.3) == 1.0 — structured market, max quality."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.3) == 1.0

    @pytest.mark.unit
    def test_high_entropy_returns_0_5(self):
        """entropy_quality(0.95) == 0.5 — chaotic market, minimum quality (upper boundary)."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.95) == 0.5

    @pytest.mark.unit
    def test_above_upper_boundary_returns_0_5(self):
        """entropy_quality(1.0) == 0.5 — above upper boundary, clamped."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(1.0) == 0.5

    @pytest.mark.unit
    def test_mid_range_entropy_between_0_5_and_1_0(self):
        """entropy_quality(0.80) is between 0.5 and 1.0 — interpolated range (0.65-0.95)."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        q = _entropy_quality(0.80)
        assert 0.5 < q < 1.0, f"Expected value between 0.5 and 1.0, got {q}"

    @pytest.mark.unit
    def test_boundary_0_65_returns_1_0(self):
        """entropy_quality(0.65) == 1.0 — exactly at lower boundary."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.65) == 1.0

    @pytest.mark.unit
    def test_below_lower_boundary_returns_1_0(self):
        """entropy_quality(0.4) == 1.0 — below lower boundary, still structured."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.4) == 1.0

    @pytest.mark.unit
    def test_typical_5m_entropy_gets_mild_penalty(self):
        """entropy_quality(0.75) > 0.8 — typical 5m bar entropy should not be heavily penalised."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        q = _entropy_quality(0.75)
        assert q > 0.8, f"Expected mild penalty for typical 5m entropy 0.75, got {q}"


class TestShannonEntropyNaNInfGuard:
    """Regression tests for BUG-02: NaN/Inf log-return guard in ShannonEntropyPlugin."""

    @pytest.mark.unit
    def test_all_nan_close_does_not_crash(self):
        """ShannonEntropyPlugin does not raise when all close prices are NaN.

        Regression for: 'autodetected range of [nan, nan] is not finite'.
        The fix filters NaN log-returns before np.histogram(), returning
        max entropy (1.0) instead of crashing. Result must be a dict (not an exception).
        """
        from src.intelligence.context.shannon_entropy import ShannonEntropyPlugin

        plugin = ShannonEntropyPlugin()
        close = np.full(30, np.nan)
        frames = {"main": pd.DataFrame({"close": close})}
        # Must not raise — _shannon_entropy returns 1.0 (max noise) on all-NaN input
        result = plugin.compute_full(frames)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_close_with_zeros_returns_empty_or_valid(self):
        """ShannonEntropyPlugin does not raise when close contains zeros.

        np.log(0) = -inf → log-return becomes -inf or nan.
        Plugin must either return {} or a valid result — never raise.
        """
        from src.intelligence.context.shannon_entropy import ShannonEntropyPlugin

        plugin = ShannonEntropyPlugin()
        close = np.array([0.0] * 5 + [100.0] * 25, dtype=float)
        frames = {"main": pd.DataFrame({"close": close})}
        # Must not raise — result may be {} or valid dict
        result = plugin.compute_full(frames)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_close_with_inf_returns_empty_or_valid(self):
        """ShannonEntropyPlugin does not raise when close contains Inf.

        Regression for 'autodetected range of [X, inf] is not finite'.
        """
        from src.intelligence.context.shannon_entropy import ShannonEntropyPlugin

        plugin = ShannonEntropyPlugin()
        close = np.array([100.0] * 25 + [np.inf] * 5, dtype=float)
        frames = {"main": pd.DataFrame({"close": close})}
        result = plugin.compute_full(frames)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_mostly_nan_with_few_valid_does_not_crash(self):
        """ShannonEntropyPlugin does not raise when < 10 finite log-returns remain after filtering.

        With < 10 valid returns, _shannon_entropy returns 1.0 (insufficient data fallback).
        The plugin then computes entropy_quality(1.0) = 0.5 and returns that.
        Result must be a dict — not raised exception.
        """
        from src.intelligence.context.shannon_entropy import ShannonEntropyPlugin

        plugin = ShannonEntropyPlugin()
        # 8 valid values → 7 log-returns < threshold of 10
        close = np.array([100.0 + i for i in range(8)] + [np.nan] * 22, dtype=float)
        frames = {"main": pd.DataFrame({"close": close})}
        result = plugin.compute_full(frames)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_normal_data_still_computes_after_guard(self):
        """ShannonEntropyPlugin still computes normally on valid finite data after the guard.

        Regression guard: the NaN filter must not break the happy path.
        """
        from src.intelligence.context.shannon_entropy import ShannonEntropyPlugin

        plugin = ShannonEntropyPlugin()
        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(rng.normal(0, 5, 50))
        frames = {"main": pd.DataFrame({"close": close})}
        result = plugin.compute_full(frames)
        assert "shannon_entropy" in result, "Expected shannon_entropy key for valid data"
        assert "entropy_quality" in result, "Expected entropy_quality key for valid data"
        assert 0.0 <= result["shannon_entropy"] <= 1.0
