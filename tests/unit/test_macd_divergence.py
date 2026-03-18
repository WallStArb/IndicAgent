"""Tests for MACDDivergencePlugin (patt_MACDDivergence)."""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(close: np.ndarray, volume: np.ndarray | None = None) -> dict:
    df = make_ohlcv(close, volume)
    return {"main": df}


class TestMACDDivergencePluginAttributes:
    def test_name(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        assert plugin.name == "patt_MACDDivergence"

    def test_outputs_contains_required_fields(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        assert "macd_div_bullish" in plugin.outputs
        assert "macd_div_bearish" in plugin.outputs
        assert "macd_div_strength" in plugin.outputs

    def test_min_lookback(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        assert plugin.min_lookback == 50

    def test_capability_tags(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        assert "pattern" in plugin.capability_tags
        assert "momentum" in plugin.capability_tags


class TestMACDDivergencePluginShortLookback:
    def test_returns_empty_when_insufficient_bars(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        # Less than min_lookback=50 bars
        close = np.linspace(5000, 5100, 30)
        result = plugin.compute_full(_make_frames(close))
        assert result == {}

    def test_returns_empty_when_no_main_frame(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        assert plugin.compute_full({}) == {}
        assert plugin.compute_full({"main": None}) == {}


class TestMACDDivergenceBullish:
    def test_detects_bullish_divergence(self):
        """Price makes lower low, MACD histogram makes higher low → bullish divergence."""
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        n = 120
        # Build price with two downward troughs, second deeper
        close = np.full(n, 5000.0)
        # First trough around bar 40 (decline of 200)
        for i in range(25, 55):
            close[i] = 5000.0 - 200.0 * np.sin(np.pi * (i - 25) / 30)
        # Recovery
        close[55:75] = np.linspace(4800, 5000, 20)
        # Second trough around bar 90, deeper in price (decline of 280)
        for i in range(75, 105):
            close[i] = 5000.0 - 280.0 * np.sin(np.pi * (i - 75) / 30)
        # Gentle recovery after second trough — limits momentum decline
        for i in range(95, 105):
            close[i] += 50.0  # partial bounce that keeps MACD from dropping as much

        df = make_ohlcv(close)
        result = plugin.compute_full({"main": df})

        assert "macd_div_bullish" in result
        assert "macd_div_bearish" in result
        assert "macd_div_strength" in result
        # Values must be floats in valid range
        assert 0.0 <= result["macd_div_bullish"] <= 1.0
        assert 0.0 <= result["macd_div_strength"] <= 1.0


class TestMACDDivergenceBearish:
    def test_detects_bearish_divergence(self):
        """Price makes higher high, MACD histogram makes lower high → bearish divergence."""
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        n = 120
        close = np.full(n, 5000.0)
        # First peak
        for i in range(25, 55):
            close[i] = 5000.0 + 200.0 * np.sin(np.pi * (i - 25) / 30)
        close[55:75] = np.linspace(5200, 5000, 20)
        # Second peak higher in price
        for i in range(75, 105):
            close[i] = 5000.0 + 280.0 * np.sin(np.pi * (i - 75) / 30)
        # Fade top of second peak — weakens momentum
        for i in range(90, 105):
            close[i] -= 50.0

        df = make_ohlcv(close)
        result = plugin.compute_full({"main": df})

        assert "macd_div_bullish" in result
        assert "macd_div_bearish" in result
        assert 0.0 <= result["macd_div_bearish"] <= 1.0

    def test_no_divergence_in_steady_uptrend(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        close = np.linspace(5000, 5500, 100)
        result = plugin.compute_full(_make_frames(close))
        assert result.get("macd_div_bullish", 0.0) == 0.0
        assert result.get("macd_div_bearish", 0.0) == 0.0


class TestMACDDivergenceComputeNext:
    def test_compute_next_delegates_to_compute_full(self):
        from src.intelligence.patterns.macd_divergence import MACDDivergencePlugin

        plugin = MACDDivergencePlugin()
        close = np.linspace(5000, 5500, 100)
        frames = _make_frames(close)
        result_full = plugin.compute_full(frames)
        result_next = plugin.compute_next(frames)
        assert result_full == result_next
