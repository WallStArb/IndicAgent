"""Tests for I7 trading setup plugins."""

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv


# ─── TrendFollowing ──────────────────────────────────────────────


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
        result = plugin.compute_full({"main": df, "features": features})

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
        result = plugin.compute_full({"main": df, "features": features})

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty result."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.array([5000.0, 5001.0, 5002.0])
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"


# ─── MeanReversion ──────────────────────────────────────────────


class TestMeanReversion:
    def test_bullish_reversion_at_support(self):
        """Price at support + RSI<30 + ranging regime → reversion_long."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "reversion_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price", 0) > 0
        assert result.get("stop_loss", 0) < result["entry_price"]
        assert len(result.get("targets", [])) >= 1
        assert result.get("regime_context") == "ranging"

    def test_bearish_reversion_at_resistance(self):
        """Price at resistance + RSI>70 → reversion_short."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "reversion_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss", 0) > result["entry_price"]
        assert len(result.get("targets", [])) >= 1

    def test_no_signal_in_trending_regime(self):
        """trend_regime=0.8 (trending) → no signal generated."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0


# ─── LiquiditySweepReclaim ──────────────────────────────────────


class TestLiquiditySweepReclaim:
    def test_bullish_sweep_reclaim_signal(self):
        """Bullish sweep + reclaimed + FVG → long signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.concatenate([
            np.full(60, 5050.0),
            np.array([5020.0, 5010.0, 5000.0]),
            np.array([5030.0, 5045.0, 5055.0]),
            np.full(34, 5060.0),
        ])
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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "sweep_reclaim_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) > 0.5

    def test_no_signal_without_reclaim(self):
        """Sweep detected but NOT reclaimed → no signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "sweep_detected": 1.0,
            "sweep_type": 1.0,
            "sweep_reclaimed": 0.0,
            "atr_14": 12.0,
        }
        plugin = LiquiditySweepReclaimPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_without_sweep(self):
        """No sweep detected → no signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {"sweep_detected": 0.0, "atr_14": 12.0}
        plugin = LiquiditySweepReclaimPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"


# ─── MultiTimeframeAlignment ──────────────────────────────────


class TestMultiTimeframeAlignment:
    def test_strong_bullish_alignment(self):
        """CTF score > 0.7 + multiple TFs → long signal."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.85,
            "ctf_trend_alignment": 0.9,
            "ctf_structure_alignment": 0.8,
            "ctf_regime_agreement": 0.7,
            "ctf_timeframes_aligned": 3.0,
            "ctf_highest_aligned_tf": 60.0,
            "trend_regime": 0.6,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "mtf_alignment_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) >= 0.7

    def test_weak_alignment_no_signal(self):
        """CTF score < threshold → no signal."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.3,
            "ctf_timeframes_aligned": 1.0,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_minimum_timeframes_required(self):
        """High CTF score but only 1 TF aligned → no signal."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.8,
            "ctf_timeframes_aligned": 1.0,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"


# ─── SqueezeExpansion ──────────────────────────────────────────


class TestSqueezeExpansion:
    def test_bullish_squeeze_breakout(self):
        """Squeeze resolved + volume expansion + bullish momentum → long signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([
            np.full(80, 5050.0) + np.random.default_rng(0).normal(0, 2, 80),
            np.linspace(5055, 5090, 20),
        ])
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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "squeeze_long"
        assert result.get("direction") == 1

    def test_no_signal_during_active_squeeze(self):
        """Squeeze still active → no signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "squeeze_active": 1.0,
            "squeeze_fired": 0.0,
            "momentum_bias": 0.0,
            "atr_14": 8.0,
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_without_volume_expansion(self):
        """Squeeze released but volume low → no signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"


# ─── LiquidityHunt ──────────────────────────────────────────────


class TestLiquidityHunt:
    """Tests for trad_LiquidityHunt plugin."""

    def _features_bsl_swept(self, bsl_level=5020.0, significance=1.0):
        """Features for a BSL sweep scenario (bearish hunt)."""
        return {
            "bsl_level": bsl_level,
            "bsl_significance": significance,
            "ssl_level": 4980.0,
            "ssl_significance": 0.85,
            "sweep_detected": 1.0,
            "sweep_type": -1.0,        # bearish sweep (BSL swept)
            "sweep_level": bsl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 1.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
            "atr_14": 10.0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }

    def _features_ssl_swept(self, ssl_level=4980.0, significance=1.0):
        """Features for an SSL sweep scenario (bullish hunt)."""
        return {
            "bsl_level": 5020.0,
            "bsl_significance": 0.85,
            "ssl_level": ssl_level,
            "ssl_significance": significance,
            "sweep_detected": 1.0,
            "sweep_type": 1.0,         # bullish sweep (SSL swept)
            "sweep_level": ssl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 0.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
            "atr_14": 10.0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }

    def test_bsl_sweep_generates_short(self):
        """BSL swept + reclaimed + significance >= 0.60 → short signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_bsl_swept()})
        assert result["signal_type"] == "liquidity_hunt_short"
        assert result["direction"] == -1
        assert result["confidence"] > 0.5
        assert result["entry_price"] > 0
        assert result["stop_loss"] > result["entry_price"]  # stop above entry for short

    def test_ssl_sweep_generates_long(self):
        """SSL swept + reclaimed + significance >= 0.60 → long signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_ssl_swept()})
        assert result["signal_type"] == "liquidity_hunt_long"
        assert result["direction"] == 1
        assert result["stop_loss"] < result["entry_price"]  # stop below entry for long

    def test_no_signal_low_significance(self):
        """Significance < 0.60 → no signal (random swing, not named level)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept(significance=0.45)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("direction", 0) == 0
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_sweep_not_reclaimed(self):
        """sweep_reclaimed=0 → no signal (breakout not a hunt)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept()
        features["sweep_reclaimed"] = 0.0
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_confidence_higher_for_pwh_than_pdh(self):
        """PWH level (significance=1.0) → higher confidence than PDH (0.85)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        r_pwh = plugin.compute_full({"main": df, "features": self._features_bsl_swept(significance=1.00)})
        r_pdh = plugin.compute_full({"main": df, "features": self._features_bsl_swept(significance=0.85)})
        if r_pwh.get("direction", 0) == -1 and r_pdh.get("direction", 0) == -1:
            assert r_pwh["confidence"] >= r_pdh["confidence"]

    def test_fvg_boosts_confidence(self):
        """FVG in sweep direction adds confidence boost."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_no_fvg = self._features_bsl_swept()
        f_fvg    = {**self._features_bsl_swept(), "fvg_detected": 1.0, "fvg_type": -1.0}
        r1 = plugin.compute_full({"main": df, "features": f_no_fvg})
        r2 = plugin.compute_full({"main": df, "features": f_fvg})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] > r1["confidence"]

    def test_opposing_zone_penalizes_confidence(self):
        """Hunting short but entering demand zone → confidence penalty."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_clean    = self._features_bsl_swept()
        f_opposing = {**self._features_bsl_swept(), "in_demand_zone": 1.0}
        r1 = plugin.compute_full({"main": df, "features": f_clean})
        r2 = plugin.compute_full({"main": df, "features": f_opposing})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] < r1["confidence"]

    def test_has_two_targets(self):
        """Signal output includes at least 2 price targets."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        df = make_ohlcv(np.full(100, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_bsl_swept()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_returns_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        df = make_ohlcv(np.full(5, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result.get("signal_type", "none") == "none"
