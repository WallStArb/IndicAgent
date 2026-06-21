"""Tests for LiquiditySweepReclaim I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestLiquiditySweepReclaim:
    def test_bullish_sweep_reclaim_signal(self):
        """Bullish sweep + reclaimed + FVG → long signal."""
        from src.intelligence.archive.trading_i7.liquidity_sweep_reclaim import (
            LiquiditySweepReclaimPlugin,
        )

        close = np.concatenate(
            [
                np.full(60, 5050.0),
                np.array([5020.0, 5010.0, 5000.0]),
                np.array([5030.0, 5045.0, 5055.0]),
                np.full(34, 5060.0),
            ]
        )
        df = make_ohlcv(close)
        features = {
            "sweep_detected": 1.0,
            "sweep_type": 1.0,
            "sweep_level": 5020.0,
            "sweep_reclaimed": 1.0,
            "sweep_depth_pct": 0.4,
            "fvg_detected": 1.0,
            "fvg_type": 1.0,
            "ob_detected": 1.0,
            "ob_type": 1.0,
            "trend_regime": 0.3,
            "atr_14": 12.0,
            "ctf_score": 0.4,
        }
        plugin = LiquiditySweepReclaimPlugin()
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

        assert result.get("signal_type") == "sweep_reclaim_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) > 0.5

    def test_no_signal_without_reclaim(self):
        """Sweep detected but NOT reclaimed → no signal."""
        from src.intelligence.archive.trading_i7.liquidity_sweep_reclaim import (
            LiquiditySweepReclaimPlugin,
        )

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "sweep_detected": 1.0,
            "sweep_type": 1.0,
            "sweep_reclaimed": 0.0,
            "atr_14": 12.0,
        }
        plugin = LiquiditySweepReclaimPlugin()
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

    def test_no_signal_without_sweep(self):
        """No sweep detected → no signal."""
        from src.intelligence.archive.trading_i7.liquidity_sweep_reclaim import (
            LiquiditySweepReclaimPlugin,
        )

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {"sweep_detected": 0.0, "atr_14": 12.0}
        plugin = LiquiditySweepReclaimPlugin()
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
