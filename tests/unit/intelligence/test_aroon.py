"""Tests for Aroon indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.aroon import AroonPlugin


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
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.lognormal(10, 0.5, n).astype(float),
        }
    )


class TestAroon:
    def test_all_output_keys_present(self):
        plugin = AroonPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "aroon_up_25" in result
        assert "aroon_down_25" in result
        assert "aroon_osc_25" in result

    def test_values_in_range(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["aroon_up_25"] <= 100.0
        assert 0.0 <= result["aroon_down_25"] <= 100.0
        assert -100.0 <= result["aroon_osc_25"] <= 100.0

    def test_oscillator_equals_up_minus_down(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv()})
        osc = result["aroon_osc_25"]
        assert abs(osc - (result["aroon_up_25"] - result["aroon_down_25"])) < 1e-6

    def test_high_at_current_bar_gives_100(self):
        """aroon_up should be 100 when highest high is the current bar."""
        df = _make_ohlcv(60)
        df = df.copy()
        df.loc[df.index[-1], "high"] = df["high"].max() * 2.0
        result = AroonPlugin().compute_full({"main": df})
        assert result["aroon_up_25"] == 100.0

    def test_low_at_current_bar_gives_100_down(self):
        """aroon_down should be 100 when lowest low is the current bar."""
        df = _make_ohlcv(60)
        df = df.copy()
        df.loc[df.index[-1], "low"] = df["low"].min() * 0.5
        result = AroonPlugin().compute_full({"main": df})
        assert result["aroon_down_25"] == 100.0

    def test_uptrend_aroon_up_dominates(self):
        """Clear uptrend: aroon_up should exceed aroon_down."""
        result = AroonPlugin().compute_full({"main": _make_ohlcv(150, trend="up")})
        assert result["aroon_osc_25"] > 0

    def test_downtrend_aroon_down_dominates(self):
        """Clear downtrend: aroon_down should exceed aroon_up."""
        result = AroonPlugin().compute_full({"main": _make_ohlcv(150, trend="down")})
        assert result["aroon_osc_25"] < 0

    def test_insufficient_data_returns_empty(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv(5)})
        assert result == {}

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = AroonPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = AroonPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert result["aroon_up_25"] == full["aroon_up_25"]
        assert result["aroon_down_25"] == full["aroon_down_25"]
