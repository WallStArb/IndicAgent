"""Tests for Stochastic RSI indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.stochastic_rsi import StochRSIPlugin


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


class TestStochRSI:
    def test_output_keys_present(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert "stoch_rsi_k_14" in result
        assert "stoch_rsi_d_14" in result

    def test_k_in_range(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["stoch_rsi_k_14"] <= 100.0

    def test_d_in_range(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["stoch_rsi_d_14"] <= 100.0

    def test_insufficient_data_returns_empty(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv(n=20)})
        assert result == {}

    def test_rsi_rising_gives_high_k(self):
        """After a downtrend (RSI depressed), a reversal upward drives RSI through
        its rolling window → current RSI is near the 14-bar max → K near 100 (> 70)."""
        # Declining phase builds avg_loss, depresses RSI to ~30-40
        declining = 5000.0 - np.arange(80) * 0.4
        # Reversal: strong rally from the low → RSI climbs monotonically
        reversal = declining[-1] + np.arange(1, 41) * 0.6
        close = np.concatenate([declining, reversal])
        df = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": np.ones(len(close)) * 1000,
            }
        )
        result = StochRSIPlugin().compute_full({"main": df})
        assert result["stoch_rsi_k_14"] > 70.0

    def test_rsi_falling_gives_low_k(self):
        """After an uptrend (RSI elevated), a reversal downward drives RSI through
        its rolling window → current RSI is near the 14-bar min → K near 0 (< 30)."""
        # Rising phase builds avg_gain, elevates RSI to ~70
        rising = 5000.0 + np.arange(80) * 0.4
        # Reversal: strong sell-off → RSI drops monotonically
        reversal = rising[-1] - np.arange(1, 41) * 0.6
        close = np.concatenate([rising, reversal])
        df = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": np.ones(len(close)) * 1000,
            }
        )
        result = StochRSIPlugin().compute_full({"main": df})
        assert result["stoch_rsi_k_14"] < 30.0

    def test_flat_rsi_gives_midpoint(self):
        """When RSI is constant (high == low == close on every bar), K should be 50."""
        n = 80
        close = np.ones(n) * 5000.0
        df = pd.DataFrame(
            {
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )
        result = StochRSIPlugin().compute_full({"main": df})
        # With no price changes, RSI = 50 constantly → StochRSI = 50
        assert result["stoch_rsi_k_14"] == 50.0

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = StochRSIPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = StochRSIPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["stoch_rsi_k_14"] - full["stoch_rsi_k_14"]) < 0.5
        assert abs(result["stoch_rsi_d_14"] - full["stoch_rsi_d_14"]) < 0.5
