"""Tests for HurstExponentPlugin (QUAL-07).

Covers:
- Plugin metadata (name, outputs, min_lookback)
- compute_full() with insufficient bars returns {}
- compute_full() returns all 3 fields with valid data
- hurst_exponent is a float in [0, 1]
- _hurst_trend_quality() mapping: H > 0.65 → >= 0.8
- _hurst_mr_quality() mapping: H < 0.35 → >= 0.8
- Random-walk H ~ 0.5 → both quality scores moderate
- Constant-price series (s=0 guard) → hurst_exponent = 0.5
- TIER_I4 includes "ctx_HurstExponent" after registration
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.intelligence.context.hurst_exponent import (
    HurstExponentPlugin,
    _hurst_mr_quality,
    _hurst_rs,
    _hurst_trend_quality,
    plugin,
)
from src.intelligence.register_plugins import TIER_I4

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frames(close: np.ndarray) -> dict:
    """Wrap a close array in the frames dict pattern used by plugins."""
    df = pd.DataFrame({"close": close})
    return {"main": df}


def _trending_close(n: int = 128) -> np.ndarray:
    """Generate a strongly trending price series (persistent H > 0.65)."""
    # Geometric random walk with strong positive drift
    rng = np.random.default_rng(42)
    returns = 0.002 + rng.normal(0, 0.001, n)
    prices = np.exp(np.cumsum(returns))
    return prices * 100.0


def _mean_reverting_close(n: int = 128) -> np.ndarray:
    """Generate a mean-reverting price series (anti-persistent H < 0.35)."""
    rng = np.random.default_rng(99)
    prices = np.zeros(n)
    prices[0] = 100.0
    mean = 100.0
    strength = 0.9  # Strong mean reversion
    for i in range(1, n):
        prices[i] = prices[i - 1] + strength * (mean - prices[i - 1]) + rng.normal(0, 0.1)
    return prices


def _random_walk_close(n: int = 128) -> np.ndarray:
    """Generate a pure random walk (H ~ 0.5)."""
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 0.005, n)
    return np.exp(np.cumsum(returns)) * 100.0


def _constant_close(n: int = 128) -> np.ndarray:
    """All prices identical (std=0 guard case)."""
    return np.full(n, 100.0)


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------

class TestHurstExponentPluginMetadata:
    def test_name(self):
        assert plugin.name == "ctx_HurstExponent"

    def test_outputs(self):
        assert plugin.outputs == frozenset({"hurst_exponent", "hurst_trend_quality", "hurst_mr_quality"})

    def test_min_lookback(self):
        assert plugin.min_lookback == 64

    def test_supports_incremental(self):
        assert plugin.supports_incremental is True

    def test_capability_tags_contains_context_and_regime(self):
        assert "context" in plugin.capability_tags
        assert "regime" in plugin.capability_tags

    def test_class_name(self):
        assert HurstExponentPlugin.__name__ == "HurstExponentPlugin"


# ---------------------------------------------------------------------------
# compute_full() — edge cases
# ---------------------------------------------------------------------------

class TestComputeFullEdgeCases:
    def test_returns_empty_when_frames_has_no_main(self):
        p = HurstExponentPlugin()
        result = p.compute_full({})
        assert result == {}

    def test_returns_empty_when_fewer_than_min_lookback_bars(self):
        p = HurstExponentPlugin()
        close = _random_walk_close(32)  # < 64 min_lookback
        result = p.compute_full(_make_frames(close))
        assert result == {}

    def test_returns_empty_when_exactly_min_lookback_minus_one(self):
        p = HurstExponentPlugin()
        close = _random_walk_close(63)  # 1 short
        result = p.compute_full(_make_frames(close))
        assert result == {}

    def test_returns_dict_when_exactly_min_lookback(self):
        p = HurstExponentPlugin()
        close = _random_walk_close(64)
        result = p.compute_full(_make_frames(close))
        assert isinstance(result, dict)
        assert len(result) == 3

    def test_constant_price_returns_hurst_05(self):
        """s=0 guard: constant series → H=0.5."""
        p = HurstExponentPlugin()
        close = _constant_close(128)
        result = p.compute_full(_make_frames(close))
        assert isinstance(result, dict)
        assert result.get("hurst_exponent") == 0.5


# ---------------------------------------------------------------------------
# compute_full() — output fields and value ranges
# ---------------------------------------------------------------------------

class TestComputeFullOutputs:
    def test_all_three_fields_present(self):
        p = HurstExponentPlugin()
        result = p.compute_full(_make_frames(_random_walk_close()))
        assert "hurst_exponent" in result
        assert "hurst_trend_quality" in result
        assert "hurst_mr_quality" in result

    def test_hurst_exponent_is_float(self):
        p = HurstExponentPlugin()
        result = p.compute_full(_make_frames(_random_walk_close()))
        assert isinstance(result["hurst_exponent"], float)

    def test_hurst_exponent_in_unit_interval(self):
        p = HurstExponentPlugin()
        result = p.compute_full(_make_frames(_random_walk_close()))
        h = result["hurst_exponent"]
        assert 0.0 <= h <= 1.0

    def test_hurst_trend_quality_is_float_in_unit_interval(self):
        p = HurstExponentPlugin()
        result = p.compute_full(_make_frames(_random_walk_close()))
        tq = result["hurst_trend_quality"]
        assert isinstance(tq, float)
        assert 0.0 <= tq <= 1.0

    def test_hurst_mr_quality_is_float_in_unit_interval(self):
        p = HurstExponentPlugin()
        result = p.compute_full(_make_frames(_random_walk_close()))
        mq = result["hurst_mr_quality"]
        assert isinstance(mq, float)
        assert 0.0 <= mq <= 1.0


# ---------------------------------------------------------------------------
# _hurst_rs() unit tests
# ---------------------------------------------------------------------------

class TestHurstRs:
    def test_returns_05_on_constant_series(self):
        close = _constant_close(64)
        h = _hurst_rs(close)
        assert h == 0.5

    def test_returns_05_when_too_short(self):
        close = _random_walk_close(8)
        h = _hurst_rs(close, min_window=16)
        assert h == 0.5

    def test_result_in_unit_interval_for_random_walk(self):
        close = _random_walk_close(128)
        h = _hurst_rs(close)
        assert 0.0 <= h <= 1.0


# ---------------------------------------------------------------------------
# Quality mapping functions
# ---------------------------------------------------------------------------

class TestHurstTrendQuality:
    def test_high_quality_for_strong_trend(self):
        """H = 0.7 (above 0.65 threshold) → quality = 1.0."""
        assert _hurst_trend_quality(0.7) >= 0.8

    def test_max_quality_at_065(self):
        assert _hurst_trend_quality(0.65) == 1.0

    def test_max_quality_above_065(self):
        assert _hurst_trend_quality(0.9) == 1.0

    def test_low_quality_for_mean_reversion(self):
        """H = 0.3 (far below 0.45 threshold) → quality = 0.3."""
        assert _hurst_trend_quality(0.3) == pytest.approx(0.3)

    def test_moderate_quality_at_random_walk(self):
        """H = 0.5 (random walk) → moderate, not extreme."""
        q = _hurst_trend_quality(0.5)
        assert 0.3 < q < 0.8

    def test_result_in_unit_interval_across_range(self):
        for h in np.linspace(0.0, 1.0, 20):
            q = _hurst_trend_quality(float(h))
            assert 0.0 <= q <= 1.0


class TestHurstMrQuality:
    def test_high_quality_for_strong_mean_reversion(self):
        """H = 0.3 (below 0.35 threshold) → quality = 1.0."""
        assert _hurst_mr_quality(0.3) >= 0.8

    def test_max_quality_at_035(self):
        assert _hurst_mr_quality(0.35) == 1.0

    def test_max_quality_below_035(self):
        assert _hurst_mr_quality(0.1) == 1.0

    def test_low_quality_for_trending(self):
        """H = 0.7 (above 0.55 threshold) → quality = 0.3."""
        assert _hurst_mr_quality(0.7) == pytest.approx(0.3)

    def test_moderate_quality_at_random_walk(self):
        """H = 0.5 (random walk) → moderate."""
        q = _hurst_mr_quality(0.5)
        assert 0.3 < q < 0.8

    def test_result_in_unit_interval_across_range(self):
        for h in np.linspace(0.0, 1.0, 20):
            q = _hurst_mr_quality(float(h))
            assert 0.0 <= q <= 1.0


# ---------------------------------------------------------------------------
# Quality consistency — H near 0.5 → both qualities are low-moderate
# ---------------------------------------------------------------------------

class TestQualityConsistency:
    def test_random_walk_both_qualities_moderate(self):
        """H ~ 0.5 → both trend and mr qualities should be between 0.3 and 0.7."""
        tq = _hurst_trend_quality(0.5)
        mq = _hurst_mr_quality(0.5)
        assert 0.3 <= tq <= 0.7
        assert 0.3 <= mq <= 0.7


# ---------------------------------------------------------------------------
# TIER_I4 registration
# ---------------------------------------------------------------------------

class TestTierRegistration:
    def test_tier_i4_includes_ctx_hurst_exponent(self):
        assert "ctx_HurstExponent" in TIER_I4
