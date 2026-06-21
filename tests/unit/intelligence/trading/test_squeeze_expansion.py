"""Tests for SqueezeExpansion I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestSqueezeExpansion:
    def test_bullish_squeeze_breakout(self):
        """Squeeze resolved + volume expansion + bullish momentum → long signal."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate(
            [
                np.full(80, 5050.0) + np.random.default_rng(0).normal(0, 2, 80),
                np.linspace(5055, 5090, 20),
            ]
        )
        volume = np.concatenate([np.full(80, 1000.0), np.full(20, 2500.0)])
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
        }
        plugin = SqueezeExpansionPlugin()
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

        assert result.get("signal_type") == "squeeze_long"
        assert result.get("direction") == 1

    def test_no_signal_during_active_squeeze(self):
        """Squeeze still active → no signal."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "squeeze_active": 1.0,
            "squeeze_fired": 0.0,
            "momentum_bias": 0.0,
            "atr_14": 8.0,
        }
        plugin = SqueezeExpansionPlugin()
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

    def test_no_signal_without_volume_expansion(self):
        """Squeeze released but volume low → no signal."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([np.full(80, 5050.0), np.linspace(5055, 5070, 20)])
        volume = np.full(100, 500.0)
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
        }
        plugin = SqueezeExpansionPlugin()
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

    def test_no_signal_in_extreme_garch_vol(self):
        """garch_vol_regime=3 (extreme) — squeeze breakout blocked regardless of setup quality."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate(
            [
                np.full(80, 5050.0) + np.random.default_rng(20).normal(0, 2, 80),
                np.linspace(5055, 5090, 20),
            ]
        )
        volume = np.concatenate([np.full(80, 1000.0), np.full(20, 2500.0)])
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
            "garch_vol_regime": 3,  # extreme vol — should block
        }
        plugin = SqueezeExpansionPlugin()
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

    def test_signal_fires_in_high_vol_not_extreme(self):
        """garch_vol_regime=2 (high, not extreme) — squeeze breakout allowed."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate(
            [
                np.full(80, 5050.0) + np.random.default_rng(21).normal(0, 2, 80),
                np.linspace(5055, 5090, 20),
            ]
        )
        volume = np.concatenate([np.full(80, 1000.0), np.full(20, 2500.0)])
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
            "garch_vol_regime": 2,  # high but not extreme — should pass
        }
        plugin = SqueezeExpansionPlugin()
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

        assert result.get("direction") == 1
        assert result.get("signal_type") == "squeeze_long"

    def test_missing_garch_squeeze_passes(self):
        """No garch_vol_regime key — gate defaults to regime=1, signal fires normally."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate(
            [
                np.full(80, 5050.0) + np.random.default_rng(22).normal(0, 2, 80),
                np.linspace(5055, 5090, 20),
            ]
        )
        volume = np.concatenate([np.full(80, 1000.0), np.full(20, 2500.0)])
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
            # no garch_vol_regime — backward compat
        }
        plugin = SqueezeExpansionPlugin()
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

        assert result.get("direction") == 1
