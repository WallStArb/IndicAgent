"""Tests for Chandelier Exit indicator plugin."""

import numpy as np
import pandas as pd
import pytest

from src.intelligence.features.i1_indicators.chandelier import ChandelierPlugin


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


class TestChandelier:
    def test_output_keys_present(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv()})
        assert "chandelier_long_22" in result
        assert "chandelier_short_22" in result

    def test_long_stop_below_highest_high(self):
        """Long stop must always be below the highest high in the window."""
        df = _make_ohlcv(100)
        result = ChandelierPlugin().compute_full({"main": df})
        highest = df["high"].iloc[-22:].max()
        assert result["chandelier_long_22"] < highest

    def test_short_stop_above_lowest_low(self):
        """Short stop must always be above the lowest low in the window."""
        df = _make_ohlcv(100)
        result = ChandelierPlugin().compute_full({"main": df})
        lowest = df["low"].iloc[-22:].min()
        assert result["chandelier_short_22"] > lowest

    def test_formula_with_known_values(self):
        """Verify formula with deterministic flat data.

        high=5010, low=4990, close=5000 for all bars.
        ATR = 20 (constant H-L since no gaps).
        long_stop  = 5010 - 3*20 = 4950
        short_stop = 4990 + 3*20 = 5050  → short > long.
        """
        n = 40
        close = np.full(n, 5000.0)
        high = np.full(n, 5010.0)
        low = np.full(n, 4990.0)
        df = pd.DataFrame(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )
        result = ChandelierPlugin().compute_full({"main": df})
        assert result["chandelier_long_22"] == pytest.approx(4950.0, abs=1.0)
        assert result["chandelier_short_22"] == pytest.approx(5050.0, abs=1.0)
        assert result["chandelier_short_22"] > result["chandelier_long_22"]

    def test_positive_values(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv()})
        assert result["chandelier_long_22"] > 0
        assert result["chandelier_short_22"] > 0

    def test_insufficient_data_returns_empty(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv(n=10)})
        assert result == {}

    def test_custom_period_and_multiplier(self):
        plugin = ChandelierPlugin(period=14, multiplier=2.0)
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "chandelier_long_22" in result  # name stays 22 by convention

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = ChandelierPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ChandelierPlugin()
        full = fresh.compute_full({"main": df.copy()})

        for key in ("chandelier_long_22", "chandelier_short_22"):
            rel_diff = abs(result[key] - full[key]) / abs(full[key])
            assert rel_diff < 0.005, f"{key}: {rel_diff:.4%} drift"
