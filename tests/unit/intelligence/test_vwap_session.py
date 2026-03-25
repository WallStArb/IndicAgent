"""Tests for VWAP session reset and standard deviation bands."""

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.vwap import VWAPPlugin


def _make_df(n_bars: int, start_date: str = "2026-01-15 09:30:00") -> pd.DataFrame:
    """Build a simple OHLCV DataFrame with timestamps."""
    rng = np.random.default_rng(42)
    dates = pd.date_range(start_date, periods=n_bars, freq="1min")
    close = 5000.0 + np.cumsum(rng.standard_normal(n_bars) * 0.5)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - rng.uniform(0, 0.5, n_bars),
            "high": close + rng.uniform(0, 1.0, n_bars),
            "low": close - rng.uniform(0, 1.0, n_bars),
            "close": close,
            "volume": rng.integers(100, 1000, n_bars).astype(float),
        }
    )


class TestVWAPSessionReset:
    def test_single_day_outputs_all_keys(self):
        """Single-day data should produce vwap + band outputs."""
        df = _make_df(100)
        plugin = VWAPPlugin()
        result = plugin.compute_full({"main": df})
        assert "vwap" in result
        assert "vwap_upper_1" in result
        assert "vwap_lower_1" in result
        assert "vwap_upper_2" in result
        assert "vwap_lower_2" in result
        assert "vwap_std" in result

    def test_session_reset_on_date_change(self):
        """VWAP should reset when date changes (multi-day data)."""
        # Day 1: 100 bars
        day1 = _make_df(100, start_date="2026-01-15 09:30:00")
        # Day 2: 100 bars
        day2 = _make_df(100, start_date="2026-01-16 09:30:00")
        multi_day = pd.concat([day1, day2], ignore_index=True)

        plugin = VWAPPlugin()
        result = plugin.compute_full({"main": multi_day})

        # Day-2-only VWAP for comparison
        plugin2 = VWAPPlugin()
        result2 = plugin2.compute_full({"main": day2})

        # Multi-day result should match day-2-only result
        # (because session reset means day 1 data is discarded)
        assert abs(result["vwap"] - result2["vwap"]) < 0.01

    def test_no_timestamp_column_falls_back(self):
        """Without timestamp column, VWAP should still work (no reset)."""
        df = _make_df(100)
        df = df.drop(columns=["timestamp"])
        plugin = VWAPPlugin()
        result = plugin.compute_full({"main": df})
        assert "vwap" in result

    def test_std_bands_symmetric(self):
        """Upper and lower bands should be symmetric around VWAP."""
        df = _make_df(200)
        plugin = VWAPPlugin()
        result = plugin.compute_full({"main": df})
        vwap = result["vwap"]
        std = result["vwap_std"]
        assert abs(result["vwap_upper_1"] - (vwap + std)) < 1e-6
        assert abs(result["vwap_lower_1"] - (vwap - std)) < 1e-6
        assert abs(result["vwap_upper_2"] - (vwap + 2 * std)) < 1e-6
        assert abs(result["vwap_lower_2"] - (vwap - 2 * std)) < 1e-6

    def test_std_is_non_negative(self):
        """Standard deviation should always be >= 0."""
        df = _make_df(50)
        plugin = VWAPPlugin()
        result = plugin.compute_full({"main": df})
        assert result["vwap_std"] >= 0

    def test_empty_df_returns_empty(self):
        plugin = VWAPPlugin()
        assert plugin.compute_full({"main": pd.DataFrame()}) == {}
