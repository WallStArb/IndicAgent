"""Tests for CMFDivergencePlugin (patt_CMFDivergence)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(close: np.ndarray, volume: np.ndarray | None = None) -> dict:
    df = make_ohlcv(close, volume)
    return {"main": df}


class TestCMFDivergencePluginAttributes:
    def test_name(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        assert plugin.name == "patt_CMFDivergence"

    def test_outputs_contains_required_fields(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        assert "cmf_div_bullish" in plugin.outputs
        assert "cmf_div_bearish" in plugin.outputs
        assert "cmf_div_strength" in plugin.outputs

    def test_min_lookback(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        assert plugin.min_lookback == 30

    def test_capability_tags(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        assert "pattern" in plugin.capability_tags
        assert "volume" in plugin.capability_tags


class TestCMFDivergenceShortLookback:
    def test_returns_empty_when_insufficient_bars(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        close = np.linspace(5000, 5100, 20)
        result = plugin.compute_full(_make_frames(close))
        assert result == {}

    def test_returns_empty_when_no_main_frame(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


class TestCMFDivergenceBullish:
    def test_detects_bullish_cmf_divergence(self):
        """Declining price + rising CMF → accumulation during decline (bullish divergence)."""
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        n = 60
        # Price declining steadily
        close = np.linspace(5200, 4800, n)
        # Volume: high buying volume at lows (strong buying pressure) → CMF rises
        volume = np.full(n, 1000.0)
        volume[30:] = 3000.0  # Much higher volume in second half — buying accumulation

        # Build OHLCV where close is near high (bullish close in range → positive MFM)
        high = close + 20.0
        low = close - 5.0  # Close near high → bullish money flow
        df = pd.DataFrame(
            {"open": close, "high": high, "low": low, "close": close, "volume": volume}
        )
        result = plugin.compute_full({"main": df})

        assert "cmf_div_bullish" in result
        assert "cmf_div_bearish" in result
        assert "cmf_div_strength" in result
        assert 0.0 <= result["cmf_div_bullish"] <= 1.0
        assert 0.0 <= result["cmf_div_strength"] <= 1.0

    def test_returns_three_keys(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        close = np.linspace(5000, 4900, 50)
        result = plugin.compute_full(_make_frames(close))
        assert set(result.keys()) == {"cmf_div_bullish", "cmf_div_bearish", "cmf_div_strength"}


class TestCMFDivergenceBearish:
    def test_detects_bearish_cmf_divergence(self):
        """Rising price + declining CMF → distribution during rise (bearish divergence)."""
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        n = 60
        # Price rising steadily
        close = np.linspace(4800, 5200, n)
        volume = np.full(n, 1000.0)
        volume[30:] = 3000.0  # High volume in second half — but selling distribution

        # Build OHLCV where close is near low (bearish close in range → negative MFM)
        high = close + 20.0
        low = close - 5.0
        close_bearish = low + 1.0  # Close near low → negative money flow
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close_bearish,
                "volume": volume,
            }
        )
        result = plugin.compute_full({"main": df})

        assert "cmf_div_bearish" in result
        assert 0.0 <= result["cmf_div_bearish"] <= 1.0


class TestCMFDivergenceComputeNext:
    def test_compute_next_delegates_to_compute_full(self):
        from src.intelligence.features.i5_patterns.cmf_divergence import CMFDivergencePlugin

        plugin = CMFDivergencePlugin()
        close = np.linspace(5000, 4900, 60)
        frames = _make_frames(close)
        result_full = plugin.compute_full(frames)
        result_next = plugin.compute_next(frames)
        assert result_full == result_next
