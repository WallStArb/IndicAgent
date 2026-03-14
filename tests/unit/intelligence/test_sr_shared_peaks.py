"""Tests for SupportResistance refactored to use shared peak detection."""

import numpy as np
import pandas as pd

from src.intelligence.structure.support_resistance import SupportResistancePlugin


def _make_ohlcv(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 5000.0 + np.cumsum(rng.standard_normal(n) * 2.0)
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame(
        {
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        }
    )


class TestSupportResistanceSharedPeaks:
    def test_outputs_all_expected_keys(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "nearest_resistance" in result
        assert "nearest_support" in result
        assert "resistance_strength" in result
        assert "support_strength" in result
        assert "sr_level_count" in result

    def test_resistance_above_price(self):
        df = _make_ohlcv()
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": df})
        current_price = float(df["close"].iloc[-1])
        assert result["nearest_resistance"] >= current_price

    def test_support_below_price(self):
        df = _make_ohlcv()
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": df})
        current_price = float(df["close"].iloc[-1])
        assert result["nearest_support"] <= current_price

    def test_short_data_returns_empty(self):
        plugin = SupportResistancePlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=20)})
        assert result == {}
