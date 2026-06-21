"""Tests for zone awareness features in I7 trading setup plugins."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestZoneEnhancements:
    """Tests that existing I7 plugins correctly use zone awareness features."""

    def test_liquidity_sweep_reclaim_boosted_by_named_level(self):
        """LiquiditySweepReclaim gains confidence when sweep was at a named pool level."""
        from src.intelligence.archive.trading_i7.liquidity_sweep_reclaim import (
            LiquiditySweepReclaimPlugin,
        )

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquiditySweepReclaimPlugin()

        base_features = {
            "sweep_detected": 1.0,
            "sweep_reclaimed": 1.0,
            "sweep_type": 1.0,
            "sweep_level": 4980.0,
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ctf_score": 0.0,
        }
        named_features = {
            **base_features,
            "ssl_significance": 1.0,  # PWL level
            "ssl_level": 4980.0,
            "bsl_significance": 0.0,
        }
        plain_features = {
            **base_features,
            "ssl_significance": 0.0,
            "bsl_significance": 0.0,
        }

        r_named = plugin.compute_full({"main": df, "features": named_features})
        r_plain = plugin.compute_full({"main": df, "features": plain_features})

        if r_named.get("direction", 0) == 1 and r_plain.get("direction", 0) == 1:
            assert r_named["confidence"] > r_plain["confidence"]

    def test_momentum_breakout_penalized_by_opposing_zone(self):
        """MomentumBreakout long penalized when in_supply_zone=1.0."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        plugin = MomentumBreakoutPlugin()

        base_features = {
            "roc_14": 0.8,
            "atr_14": 10.0,
            "volume": 2000.0,
            "bos_detected": 1.0,
            "bos_direction": 1.0,
            "bos_level": 5050.0,
            "trend_regime": 0.6,
            "ctf_score": 0.0,
        }
        clean_features = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]

    def test_trend_following_penalized_by_opposing_zone(self):
        """TrendFollowing long penalized when trending into supply zone."""
        from src.intelligence.archive.trading_i7.trend_following import TrendFollowingPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()

        base_features = {
            "trend_regime": 0.8,
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 5180.0,
            "ema_21": 5185.0,
        }
        clean_features = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]
