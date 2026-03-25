"""Tests for Chaikin Money Flow indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.cmf import CMFPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.001, n)),
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.lognormal(10, 0.5, n).astype(float),
        }
    )


class TestCMF:
    def test_output_key_present(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "cmf_20" in result

    def test_value_in_range(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert -1.0 <= result["cmf_20"] <= 1.0

    def test_insufficient_data_returns_empty(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_buying_pressure_positive(self):
        """Close near high of every bar → CMF strongly positive."""
        rng = np.random.default_rng(0)
        n = 60
        high = 5001.0 + rng.uniform(0, 1, n)
        low = 4999.0 + rng.uniform(0, 0.1, n)
        close = high - rng.uniform(0.01, 0.05, n)  # close near high
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] > 0.5

    def test_selling_pressure_negative(self):
        """Close near low of every bar → CMF strongly negative."""
        rng = np.random.default_rng(0)
        n = 60
        high = 5001.0 + rng.uniform(0, 1, n)
        low = 4999.0 + rng.uniform(0, 0.1, n)
        close = low + rng.uniform(0.01, 0.05, n)  # close near low
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] < -0.5

    def test_zero_range_bars_handled(self):
        """Bars where high == low should not raise (MFM = 0)."""
        df = _make_ohlcv(50)
        df["high"] = df["close"]
        df["low"] = df["close"]
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] == 0.0

    def test_incremental_matches_full(self):
        """compute_next fed bar-by-bar should match a fresh compute_full."""
        df = _make_ohlcv(200)

        plugin = CMFPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = CMFPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["cmf_20"] - full["cmf_20"]) < 1e-6
