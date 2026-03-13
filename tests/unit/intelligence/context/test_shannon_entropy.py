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
        assert result["shannon_entropy"] < 0.3, (
            f"Expected low entropy for flat price series, got {result['shannon_entropy']}"
        )

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
        assert result["shannon_entropy"] > 0.7, (
            f"Expected high entropy for uniform spread series, got {result['shannon_entropy']}"
        )

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
        """entropy_quality(0.9) == 0.5 — chaotic market, minimum quality."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.9) == 0.5

    @pytest.mark.unit
    def test_mid_range_entropy_between_0_5_and_1_0(self):
        """entropy_quality(0.6) is between 0.5 and 1.0 — interpolated range."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        q = _entropy_quality(0.6)
        assert 0.5 < q < 1.0, f"Expected value between 0.5 and 1.0, got {q}"

    @pytest.mark.unit
    def test_boundary_0_4_returns_1_0(self):
        """entropy_quality(0.4) == 1.0 — exactly at lower boundary."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.4) == 1.0

    @pytest.mark.unit
    def test_boundary_0_8_returns_0_5(self):
        """entropy_quality(0.8) == 0.5 — exactly at upper boundary."""
        from src.intelligence.context.shannon_entropy import _entropy_quality

        assert _entropy_quality(0.8) == 0.5
