"""Tests for Parabolic SAR indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.parabolic_sar import PSARPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.003, 0.006, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestPSAR:
    def test_output_keys_present(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert "psar_value" in result
        assert "psar_direction" in result

    def test_direction_is_valid(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert result["psar_direction"] in (1.0, -1.0)

    def test_psar_value_positive(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert result["psar_value"] > 0

    def test_uptrend_bullish_direction(self):
        """Strong uptrend → PSAR should be bullish (1.0) and below price."""
        df = _make_ohlcv(200, trend="up")
        result = PSARPlugin().compute_full({"main": df})
        assert result["psar_direction"] == 1.0
        assert result["psar_value"] < float(df["close"].iloc[-1])

    def test_downtrend_bearish_direction(self):
        """Strong downtrend → PSAR should be bearish (-1.0) and above price."""
        df = _make_ohlcv(200, trend="down")
        result = PSARPlugin().compute_full({"main": df})
        assert result["psar_direction"] == -1.0
        assert result["psar_value"] > float(df["close"].iloc[-1])

    def test_insufficient_data_returns_empty(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_incremental_matches_full(self):
        """compute_next bar-by-bar should match fresh compute_full."""
        df = _make_ohlcv(200)

        plugin = PSARPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = PSARPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert result["psar_direction"] == full["psar_direction"]
        assert abs(result["psar_value"] - full["psar_value"]) / abs(full["psar_value"]) < 0.005

    def test_custom_af_params(self):
        plugin = PSARPlugin(af_step=0.01, af_max=0.10)
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "psar_value" in result
