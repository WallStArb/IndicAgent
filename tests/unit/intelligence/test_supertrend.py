"""Tests for Supertrend indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.supertrend import SupertrendPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "up") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 2.0 + rng.standard_normal(n) * 0.5
    elif trend == "down":
        close = 5100.0 - np.arange(n) * 2.0 + rng.standard_normal(n) * 0.5
    else:
        close = 5000.0 + rng.standard_normal(n) * 0.5
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame({
        "open": close - rng.uniform(0, 0.5, n),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(100, 1000, n).astype(float),
    })


class TestSupertrend:
    def test_outputs_expected_keys(self):
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "supertrend_value" in result
        assert "supertrend_dir" in result

    def test_direction_is_plus_or_minus_one(self):
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["supertrend_dir"] in (1, -1, 1.0, -1.0)

    def test_uptrend_data_bullish(self):
        """Strong uptrend should produce bullish direction."""
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=200, trend="up")})
        assert result["supertrend_dir"] == 1

    def test_downtrend_data_bearish(self):
        """Strong downtrend should produce bearish direction."""
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=200, trend="down")})
        assert result["supertrend_dir"] == -1

    def test_value_is_positive(self):
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["supertrend_value"] > 0

    def test_short_data_returns_empty(self):
        plugin = SupertrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_custom_params(self):
        plugin = SupertrendPlugin(period=7, multiplier=2.0)
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "supertrend_value" in result

    def test_uses_upstream_atr_when_available(self):
        """Should still work with upstream features available."""
        plugin = SupertrendPlugin()
        df = _make_ohlcv(n=100)
        result = plugin.compute_full({"main": df, "features": {"atr_14": 5.0}})
        assert "supertrend_value" in result
