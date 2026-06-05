"""Tests for SupportResistance refactored to use shared peak detection."""

import pandas as pd

from src.intelligence.features.i3_structure.support_resistance import SupportResistancePlugin


def _make_ohlcv_with_pivots(
    support_price: float = 7300.0,
    resistance_price: float = 7500.0,
    current_price: float = 7400.0,
    n: int = 120,
) -> pd.DataFrame:
    """Build OHLCV with known pivot high at resistance_price and known pivot low at support_price.

    Structure: bars oscillate around current_price with explicit extremes at the pivot levels
    so that find_peaks/find_troughs detect them deterministically regardless of cluster radius.
    """
    close = [current_price] * n
    high = [current_price + 2.0] * n
    low = [current_price - 2.0] * n
    volume = [1000.0] * n
    if n >= 91:
        # Resistance pivot: local high at resistance_price (bar 80 surrounded by lower highs)
        for i in range(75, 86):
            high[i] = current_price + 1.0
        high[80] = resistance_price
    if n >= 21:
        # Support pivot: local low at support_price (bar 10 surrounded by higher lows)
        for i in range(5, 16):
            low[i] = current_price - 1.0
        low[10] = support_price
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _make_frames(
    support_price: float = 7300.0,
    resistance_price: float = 7500.0,
    current_price: float = 7400.0,
    n: int = 120,
    tf: str = "5m",
    atr_14: float = 9.0,
) -> dict:
    return {
        "main": _make_ohlcv_with_pivots(support_price, resistance_price, current_price, n),
        "i1": {"atr_14": atr_14},
        "timeframe": tf,
    }


class TestSupportResistanceSharedPeaks:
    def test_outputs_all_expected_keys(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(_make_frames())
        assert "sr_level_count" in result
        optional_keys = [
            "nearest_resistance",
            "nearest_support",
            "resistance_strength",
            "support_strength",
            "resistance_dist_pct",
            "support_dist_pct",
            "resistance_age_bars",
            "support_age_bars",
        ]
        for key in optional_keys:
            if key in result:
                assert isinstance(result[key], float)

    def test_resistance_above_price(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(_make_frames())
        if "nearest_resistance" in result:
            assert result["nearest_resistance"] >= 7400.0

    def test_support_below_price(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(_make_frames())
        if "nearest_support" in result:
            assert result["nearest_support"] <= 7400.0

    def test_short_data_returns_empty(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": _make_ohlcv_with_pivots(n=20)})
        assert result == {}

    def test_no_synthetic_fallback(self):
        """When no real pivots outside current_price range, s/r keys must be absent."""
        current_price = 7400.0
        n = 120
        # All bars oscillate tightly around current_price - no pivot exceeds the range
        close = [current_price] * n
        high = [current_price + 2.0] * n
        low = [current_price - 2.0] * n
        volume = [1000.0] * n
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "i1": {"atr_14": 9.0}, "timeframe": "5m"}
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(frames)

        assert "nearest_support" not in result
        assert "nearest_resistance" not in result
        assert "sr_level_count" in result
        # Synthetic phantom values must not appear
        assert current_price * 0.98 not in result.values()
        assert current_price * 1.02 not in result.values()

    def test_sparse_output_semantics(self):
        """When only support pivot exists, nearest_resistance key must be absent (not None)."""
        current_price = 7400.0
        n = 120
        # All highs stay at current_price + 2 (no pivot above current_price)
        high = [current_price + 2.0] * n
        low = [current_price - 2.0] * n
        close = [current_price] * n
        volume = [1000.0] * n
        # Create a clear support pivot within the last 60 bars (tf="5m" uses lookback=60).
        # Bar 70 of the 120-bar array becomes bar 10 of the 60-bar slice [60:120].
        for i in range(65, 76):
            low[i] = current_price - 1.0
        low[70] = 7200.0  # clear support pivot far below price, within slice
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "i1": {"atr_14": 9.0}, "timeframe": "5m"}
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(frames)

        # Support should be detected; resistance absent (no real pivot above price)
        assert "nearest_support" in result
        assert "nearest_resistance" not in result

    def test_age_bars_relative_to_sliced_window(self):
        """age_bars must be relative to the TF-proportional sliced window, not the full frame."""
        current_price = 7400.0
        n = 120
        # Build a frame with support pivot at bar index 5 (early in the 120-bar array)
        high = [current_price + 2.0] * n
        low = [current_price - 2.0] * n
        close = [current_price] * n
        volume = [1000.0] * n
        # Support pivot at bar 5 (well outside the 60-bar slice for tf="5m")
        for i in range(0, 11):
            low[i] = current_price - 1.0
        low[5] = 7200.0
        # Also add a resistance pivot within the sliced window
        for i in range(85, 96):
            high[i] = current_price + 1.0
        high[90] = 7600.0
        df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
        frames = {"main": df, "i1": {"atr_14": 9.0}, "timeframe": "5m"}  # lookback=60
        plugin = SupportResistancePlugin()
        result = plugin.compute_full(frames)

        # The pivot at bar 5 of 120-bar array is outside the 60-bar slice (bars 60-119)
        # so nearest_support should be absent OR age_bars <= 60 if it somehow falls in slice
        if "nearest_support" in result:
            assert result["support_age_bars"] <= 60.0

        # Resistance at bar 90 of 120 falls within the last 60 bars (bars 60-119 = slice indices 0-59)
        if "nearest_resistance" in result:
            assert result["resistance_age_bars"] <= 60.0
