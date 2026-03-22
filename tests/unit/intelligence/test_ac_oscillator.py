"""Tests for AC Oscillator (Bill Williams) I1 plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.ac_oscillator import plugin


def make_ohlcv(n: int, base: float = 100.0, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = base + np.cumsum(rng.normal(0, 0.5, n))
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.normal(0, 0.2, n)
    vols = rng.uniform(1000, 5000, n)
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    )


class TestACOscillatorPlugin:
    def test_outputs_present(self):
        """50-bar OHLCV returns dict with 'ao' and 'ac' keys."""
        df = make_ohlcv(50)
        result = plugin.compute_full({"main": df})
        assert "ao" in result
        assert "ac" in result

    def test_formula_correctness(self):
        """ao and ac match the pandas rolling formula to 1e-6 tolerance."""
        df = make_ohlcv(50)
        result = plugin.compute_full({"main": df})
        mid = (df["high"] + df["low"]) / 2
        ao_expected = mid.rolling(5).mean() - mid.rolling(34).mean()
        ac_expected = ao_expected - ao_expected.rolling(5).mean()
        assert abs(result["ao"] - float(ao_expected.iloc[-1])) < 1e-6
        assert abs(result["ac"] - float(ac_expected.iloc[-1])) < 1e-6

    def test_insufficient_bars_39(self):
        """39-bar DataFrame returns empty dict (below min_lookback of 40)."""
        df = make_ohlcv(39)
        result = plugin.compute_full({"main": df})
        assert result == {}

    def test_insufficient_bars_40(self):
        """40-bar DataFrame returns dict with 'ao' and 'ac' (exactly at min_lookback)."""
        df = make_ohlcv(40)
        result = plugin.compute_full({"main": df})
        assert "ao" in result
        assert "ac" in result

    def test_output_types(self):
        """ao and ac are float (not int, not None)."""
        df = make_ohlcv(50)
        result = plugin.compute_full({"main": df})
        assert isinstance(result["ao"], float)
        assert isinstance(result["ac"], float)
        assert result["ao"] is not None
        assert result["ac"] is not None

    def test_no_features_dependency(self):
        """frames without 'features' key still returns ao and ac (pure OHLCV)."""
        df = make_ohlcv(50)
        result = plugin.compute_full({"main": df})
        assert "ao" in result
        assert "ac" in result

    def test_none_df(self):
        """frames['main'] = None returns empty dict."""
        result = plugin.compute_full({"main": None})
        assert result == {}

    def test_ao_positive_uptrend(self):
        """Constructed uptrend DataFrame produces ao > 0 (SMA5 > SMA34 of midpoint)."""
        n = 100
        # Build a strict uptrend: midpoint increases monotonically
        closes = 100.0 + np.arange(n) * 2.0  # strong uptrend
        highs = closes + 0.5
        lows = closes - 0.5
        opens = closes
        vols = np.ones(n) * 1000.0
        df = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": vols,
            }
        )
        result = plugin.compute_full({"main": df})
        assert result["ao"] > 0, f"Expected ao > 0 for uptrend, got {result['ao']}"
