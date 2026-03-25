"""Tests for ADX deduplication refactor."""

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.adx import ADXPlugin


def _make_ohlc(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 5000.0 + np.cumsum(rng.standard_normal(n) * 2.0)
    high = close + rng.uniform(0, 3, n)
    low = close - rng.uniform(0, 3, n)
    return pd.DataFrame({"high": high, "low": low, "close": close})


class TestADXRefactor:
    def test_output_values_in_range(self):
        plugin = ADXPlugin()
        result = plugin.compute_full({"main": _make_ohlc()})
        assert 0 <= result["adx_14"] <= 100
        assert 0 <= result["plus_di_14"] <= 100
        assert 0 <= result["minus_di_14"] <= 100

    def test_state_populated_after_compute_full(self):
        """compute_full should populate _state (for compute_next protocol)."""
        plugin = ADXPlugin()
        plugin.compute_full({"main": _make_ohlc()})
        assert "adx_14" in plugin._state
        assert "smoothed_plus_dm" in plugin._state["adx_14"]

    def test_short_data_returns_empty(self):
        plugin = ADXPlugin()
        result = plugin.compute_full({"main": _make_ohlc(n=10)})
        assert result == {}
