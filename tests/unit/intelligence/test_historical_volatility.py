"""Tests for Historical Volatility indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.historical_volatility import HistoricalVolatilityPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, vol: float = 0.005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, vol, n)
    close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.002, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestHistoricalVolatility:
    def test_output_keys_present(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv()})
        assert "hv_20" in result
        assert "hv_ratio_20" in result

    def test_hv_positive(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv()})
        assert result["hv_20"] > 0.0

    def test_hv_annualized_scale(self):
        """For 0.5% per-bar vol, annualized HV should be in reasonable range (> 5% annual)."""
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.005)})
        assert result["hv_20"] > 0.05  # at least 5% annualized

    def test_insufficient_data_returns_empty(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(n=10)})
        assert result == {}

    def test_higher_vol_gives_higher_hv(self):
        low_result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.001)})
        high_result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.02)})
        assert high_result["hv_20"] > low_result["hv_20"]

    def test_ratio_near_one_for_stable_vol(self):
        """With constant volatility throughout, ratio should be close to 1.0."""
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(n=200, vol=0.005)})
        assert 0.5 < result["hv_ratio_20"] < 2.0

    def test_ratio_elevated_after_vol_spike(self):
        """Vol spike at end of series → ratio > 1.0."""
        rng = np.random.default_rng(0)
        low_ret = rng.normal(0, 0.001, 60)
        high_ret = rng.normal(0, 0.02, 20)   # 20x vol spike
        returns = np.concatenate([low_ret, high_ret])
        close = 5000.0 * np.cumprod(1 + returns)
        df = pd.DataFrame({
            "open": close, "high": close * 1.001, "low": close * 0.999,
            "close": close, "volume": np.ones(len(returns)) * 1000,
        })
        result = HistoricalVolatilityPlugin().compute_full({"main": df})
        assert result["hv_ratio_20"] > 1.5

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = HistoricalVolatilityPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = HistoricalVolatilityPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["hv_20"] - full["hv_20"]) / full["hv_20"] < 0.005  # 0.5% tolerance
        assert abs(result["hv_ratio_20"] - full["hv_ratio_20"]) < 0.05
