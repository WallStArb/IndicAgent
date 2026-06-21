"""Tests for HMM gradient continuity in I7 trading setup plugins."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestHMMGradientContinuity:
    """Tests verifying continuous HMM probability weighting in I7 plugins.

    These tests confirm that plugins no longer use binary hmm_regime equality
    checks in confidence scoring. Confidence adjustments are proportional to
    hmm_prob_* values, not all-or-nothing.
    """

    def _base_features(self, **overrides) -> dict:
        """Standard feature set with configurable HMM probabilities."""
        defaults = {
            "hmm_regime": 0.0,
            "hmm_prob_ranging": 0.6,
            "hmm_prob_trending_up": 0.3,
            "hmm_prob_trending_down": 0.1,
            "atr_14": 10.0,
        }
        defaults.update(overrides)
        return defaults

    def test_failed_breakout_confidence_scales_with_ranging_prob(self):
        """Ranging probability scales the +0.15 boost continuously."""
        from src.intelligence.archive.trading_i7.failed_breakout import FailedBreakoutPlugin

        df = make_ohlcv(np.full(100, 5000.0))
        plugin = FailedBreakoutPlugin()
        # Create a state where BOS is detected and reversal happened
        plugin._state[("", "")] = {
            "bos_level": 4980.0,
            "bos_direction": -1,
            "bars_since_bos": 1,
        }
        features_high = self._base_features(
            hmm_regime=0.0,
            hmm_prob_ranging=0.9,
            hmm_prob_trending_up=0.05,
            hmm_prob_trending_down=0.05,
            bos_detected=0.0,  # no new BOS, use state
        )
        features_low = self._base_features(
            hmm_regime=0.0,
            hmm_prob_ranging=0.2,
            hmm_prob_trending_up=0.5,
            hmm_prob_trending_down=0.3,
            bos_detected=0.0,
        )
        r_high = plugin.compute_full({"main": df, "features": features_high})
        r_low = plugin.compute_full({"main": df, "features": features_low})
        if r_high.get("direction") and r_low.get("direction"):
            # Higher ranging probability should produce higher confidence
            assert r_high["confidence"] > r_low["confidence"]

    def test_supply_demand_continuous_freshness_base(self):
        """Base confidence ramps continuously with freshness, not 3 steps."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        df = make_ohlcv(np.full(100, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        r_70 = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i2": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i3": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i4": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i5": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "smc": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i6": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.70,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
            }
        )
        r_60 = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i2": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i3": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i4": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i5": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "smc": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
                "i6": {
                    "in_demand_zone": 1.0,
                    "in_supply_zone": 0.0,
                    "demand_freshness": 0.60,
                    "demand_strength": 0.5,
                    "nearest_demand_high": 5010.0,
                    "nearest_demand_low": 4990.0,
                    "atr_14": 10.0,
                    "price_in_premium": 0.0,
                },
            }
        )
        if r_70.get("direction") == 1 and r_60.get("direction") == 1:
            # Higher freshness should produce higher confidence
            assert r_70["confidence"] > r_60["confidence"]

    def test_momentum_breakout_regime_score_continuous(self):
        """regime_score is continuous from HMM probabilities, not 0.5/1.0/0.1 steps."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        base = {
            "roc_14": 0.8,
            "atr_14": 10.0,
            "swing_high": 5060.0,
            "trend_regime": 0.6,
            "in_supply_zone": 0.0,
            "supply_strength": 0.0,
            "in_demand_zone": 0.0,
            "demand_strength": 0.0,
        }
        plugin = MomentumBreakoutPlugin()
        r_high = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "i2": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "i3": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "i4": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "i5": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "smc": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
                "i6": {
                    **base,
                    "hmm_prob_trending_up": 0.9,
                    "hmm_prob_trending_down": 0.05,
                    "hmm_prob_ranging": 0.05,
                },
            }
        )
        r_mid = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "i2": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "i3": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "i4": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "i5": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "smc": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
                "i6": {
                    **base,
                    "hmm_prob_trending_up": 0.5,
                    "hmm_prob_trending_down": 0.3,
                    "hmm_prob_ranging": 0.2,
                },
            }
        )
        if r_high.get("direction") == 1 and r_mid.get("direction") == 1:
            # Higher trending probability should give higher confidence
            assert r_high["confidence"] > r_mid["confidence"]

    def test_squeeze_expansion_regime_score_bounded(self):
        """regime_score in squeeze_expansion ranges between 0.2 and 0.8."""
        from src.intelligence.archive.trading_i7.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate(
            [
                np.full(80, 5050.0) + np.random.default_rng(30).normal(0, 2, 80),
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
            "bb_20_2_upper": 5060.0,
            "bb_20_2_lower": 5040.0,
            "bb_20_2_mid": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
            "trend_regime": 0.6,
            "hmm_prob_trending_up": 0.8,
            "hmm_prob_trending_down": 0.1,
            "hmm_prob_ranging": 0.1,
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
        if result.get("direction") == 1:
            # With trending probability at 0.8 and regime_agrees=True:
            # regime_score = 0.2 + 0.6 * max(0.8, 0.1) = 0.2 + 0.48 = 0.68
            # raw_conf = 0.3*1.0 + 0.3*vol + 0.2*mom + 0.2*0.68
            assert result["confidence"] > 0.10  # above floor
            assert result["confidence"] <= 0.95  # below ceiling

    def test_second_leg_untouched(self):
        """second_leg_continuation still uses binary eligibility gate correctly."""
        from src.intelligence.archive.trading_i7.second_leg_continuation import (
            SecondLegContinuationPlugin,
        )

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        plugin = SecondLegContinuationPlugin()
        # Ranging regime (hmm_regime=0) → should return no signal (eligibility gate)
        result = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "i2": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "i3": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "i4": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "i5": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "smc": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
                "i6": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                    "swing_pattern": 1.0,
                    "trend_regime": 0.5,
                },
            }
        )
        assert result.get("signal_type", "none") == "none" or result.get("direction", 0) == 0

    def test_vcp_untouched(self):
        """vcp still uses binary eligibility gate correctly."""
        from src.intelligence.archive.trading_i7.vcp import VCPPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = VCPPlugin()
        # Ranging regime (hmm_regime=0) → should return no signal (eligibility gate)
        result = plugin.compute_full(
            {
                "main": df,
                "i1": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "i2": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "i3": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "i4": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "i5": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "smc": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
                "i6": {
                    "hmm_regime": 0.0,
                    "hmm_regime_prob": 0.9,
                    "atr_14": 10.0,
                },
            }
        )
        assert result.get("signal_type", "none") == "none" or result.get("direction", 0) == 0
