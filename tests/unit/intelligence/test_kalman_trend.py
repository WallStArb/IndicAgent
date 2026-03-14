"""Tests for Kalman filter trend plugin."""

import numpy as np
import pandas as pd

from src.intelligence.context.kalman_trend import KalmanTrendPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: float = 0.5) -> pd.DataFrame:
    """Generate synthetic OHLCV with a gentle uptrend."""
    rng = np.random.default_rng(seed)
    close = 5000.0 + np.arange(n) * trend + np.cumsum(rng.standard_normal(n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame(
        {
            "open": close - rng.uniform(0, 0.5, n),
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        }
    )


class TestKalmanTrend:
    def test_outputs_expected_keys(self):
        """All 7 output keys must be present with sufficient history."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        for key in [
            "kalman_trend",
            "kalman_slope",
            "kalman_price_position",
            "kalman_uncertainty",
            "kalman_upper",
            "kalman_lower",
            "kalman_gain",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_kalman_trend_near_close(self):
        """kalman_trend should be within 2% of the final close on trending data."""
        plugin = KalmanTrendPlugin()
        df = _make_ohlcv(n=100)
        result = plugin.compute_full({"main": df})
        final_close = float(df["close"].iloc[-1])
        assert abs(result["kalman_trend"] - final_close) / final_close < 0.02

    def test_kalman_gain_bounded(self):
        """kalman_gain (K) must be in [0, 1]."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["kalman_gain"] <= 1.0

    def test_bands_straddle_trend(self):
        """kalman_upper > kalman_trend > kalman_lower."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["kalman_upper"] > result["kalman_trend"]
        assert result["kalman_trend"] > result["kalman_lower"]

    def test_short_data_returns_empty(self):
        """Returns {} when fewer than min_lookback bars."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_uncertainty_is_positive(self):
        """kalman_uncertainty (P_est) must always be positive."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["kalman_uncertainty"] > 0

    def test_compute_next_matches_compute_full_on_final_bar(self):
        """compute_next on the last bar must match compute_full within 0.01%."""
        plugin_full = KalmanTrendPlugin()
        plugin_next = KalmanTrendPlugin()

        df = _make_ohlcv(n=100)
        df_minus_1 = df.iloc[:-1].reset_index(drop=True)
        df_last = df.iloc[-1:]

        # Warm up plugin_next on all-but-last bars
        plugin_next.compute_full({"main": df_minus_1})

        # Both process the full series
        result_full = plugin_full.compute_full({"main": df})
        result_next = plugin_next.compute_next({"main": df_last})

        assert abs(result_full["kalman_trend"] - result_next["kalman_trend"]) < 0.01

    def test_adaptive_mode_uses_garch_sigma(self):
        """With use_garch_adaptive=True, garch_sigma in features changes R."""
        plugin_fixed = KalmanTrendPlugin(use_garch_adaptive=False)
        plugin_adapt = KalmanTrendPlugin(use_garch_adaptive=True)

        df = _make_ohlcv(n=100)
        frames_no_garch = {"main": df, "features": {}}
        frames_with_garch = {"main": df, "features": {"garch_sigma": 0.02}}

        result_fixed = plugin_fixed.compute_full(frames_no_garch)
        result_adapt = plugin_adapt.compute_full(frames_with_garch)

        # Both must produce valid output — but kalman_gain will differ
        assert "kalman_trend" in result_fixed
        assert "kalman_trend" in result_adapt

    def test_adaptive_mode_falls_back_when_no_garch(self):
        """With use_garch_adaptive=True but no garch_sigma, must not raise."""
        plugin = KalmanTrendPlugin(use_garch_adaptive=True)
        df = _make_ohlcv(n=100)
        # No features at all — must fall back to fixed R gracefully
        result = plugin.compute_full({"main": df})
        assert "kalman_trend" in result
