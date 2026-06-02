"""Tests for TrendFollowing I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestTrendFollowing:
    def test_bullish_signal_in_uptrend(self):
        """Strong bullish regime + confirming structure → long signal."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.8,
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 5180.0,
            "ema_21": 5185.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result.get("signal_type") == "trend_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price", 0) > 0
        assert result.get("stop_loss", 0) < result["entry_price"]
        assert len(result.get("targets", [])) >= 1

    def test_bearish_signal_in_downtrend(self):
        """Strong bearish regime + confirming structure → short signal."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.linspace(5200, 5000, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": -0.8,
            "trend_confidence": 0.75,
            "swing_pattern": -1.0,
            "trend_strength": -0.7,
            "ctf_score": -0.6,
            "atr_14": 10.0,
            "sma_20": 5020.0,
            "ema_21": 5015.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result.get("signal_type") == "trend_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss", 0) > result["entry_price"]

    def test_no_signal_in_weak_regime(self):
        """Weak/neutral regime → no signal generated."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.full(100, 5100.0) + np.random.default_rng(0).normal(0, 2, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.2,
            "trend_confidence": 0.3,
            "swing_pattern": 0.0,
            "trend_strength": 0.1,
            "ctf_score": 0.1,
            "atr_14": 10.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty result."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.array([5000.0, 5001.0, 5002.0])
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {} or result.get("signal_type", "none") == "none"
