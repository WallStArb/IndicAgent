"""Tests for MeanReversion I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestMeanReversion:
    def test_bullish_reversion_at_support(self):
        """Price at support + RSI<30 + ranging regime → reversion_long."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(1).normal(0, 2, 100)
        close[-1] = 4980.0  # price near support
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.1,
            "vol_regime": 0.5,
            "rsi_14": 25.0,
            "rsi_div_bullish": 0.0,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5000.0,
            "bb_upper": 5020.0,
            "bb_lower": 4980.0,
            "sr_nearest_support": 4975.0,
            "sr_nearest_resistance": 5025.0,
            "atr_14": 10.0,
            "ctf_score": 0.0,
        }
        plugin = MeanReversionPlugin()
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

        assert result.get("signal_type") == "reversion_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price", 0) > 0
        assert result.get("stop_loss", 0) < result["entry_price"]
        assert len(result.get("targets", [])) >= 1
        assert result.get("regime_context") == "ranging"

    def test_bearish_reversion_at_resistance(self):
        """Price at resistance + RSI>70 → reversion_short."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(2).normal(0, 2, 100)
        close[-1] = 5020.0  # price near resistance
        df = make_ohlcv(close)
        features = {
            "trend_regime": -0.1,
            "vol_regime": 0.5,
            "rsi_14": 75.0,
            "rsi_div_bullish": 0.0,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5000.0,
            "bb_upper": 5020.0,
            "bb_lower": 4980.0,
            "sr_nearest_support": 4975.0,
            "sr_nearest_resistance": 5025.0,
            "atr_14": 10.0,
            "ctf_score": 0.0,
        }
        plugin = MeanReversionPlugin()
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

        assert result.get("signal_type") == "reversion_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss", 0) > result["entry_price"]
        assert len(result.get("targets", [])) >= 1

    def test_no_signal_in_trending_regime(self):
        """trend_regime=0.8 (trending) → no signal generated."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.8,
            "vol_regime": 0.5,
            "rsi_14": 25.0,
            "rsi_div_bullish": 0.5,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5100.0,
            "atr_14": 10.0,
            "ctf_score": 0.0,
        }
        plugin = MeanReversionPlugin()
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

    def test_no_signal_when_near_kalman_fair_value(self):
        """kalman_price_position < 1.0σ — price at fair value, no extension to revert."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(10).normal(0, 2, 100)
        close[-1] = 4980.0
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.1,
            "vol_regime": 0.5,
            "rsi_14": 25.0,
            "rsi_div_bullish": 0.0,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5000.0,
            "atr_14": 10.0,
            "kalman_price_position": 0.5,  # < 1.0 — near fair value
        }
        plugin = MeanReversionPlugin()
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

    def test_signal_fires_when_kalman_price_displaced(self):
        """kalman_price_position >= 1.0σ — price is displaced, reversion valid."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(11).normal(0, 2, 100)
        close[-1] = 4980.0
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.1,
            "vol_regime": 0.5,
            "rsi_14": 25.0,
            "rsi_div_bullish": 0.0,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5000.0,
            "atr_14": 10.0,
            "kalman_price_position": -1.5,  # displaced 1.5σ below fair value
        }
        plugin = MeanReversionPlugin()
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

        assert result.get("direction") == 1  # long reversion
        assert result.get("signal_type") == "reversion_long"

    def test_missing_kalman_data_mean_reversion_unaffected(self):
        """No kalman_price_position in features → gate skipped, existing behavior unchanged."""
        from src.intelligence.archive.trading_i7.mean_reversion import MeanReversionPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(12).normal(0, 2, 100)
        close[-1] = 4980.0
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.1,
            "vol_regime": 0.5,
            "rsi_14": 25.0,
            "rsi_div_bullish": 0.0,
            "rsi_div_bearish": 0.0,
            "bb_middle": 5000.0,
            "atr_14": 10.0,
            # no kalman_price_position — gate must be skipped
        }
        plugin = MeanReversionPlugin()
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

        # Should still fire (same as existing test_bullish_reversion_at_support)
        assert result.get("direction") == 1
