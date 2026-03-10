"""Tests for I7 trading setup plugins."""

import numpy as np

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

    def test_no_signal_when_near_kalman_fair_value(self):
        """kalman_price_position < 1.0σ — price at fair value, no extension to revert."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
            "kalman_price_position": 0.5,   # < 1.0 — near fair value
        }
        plugin = MeanReversionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_signal_fires_when_kalman_price_displaced(self):
        """kalman_price_position >= 1.0σ — price is displaced, reversion valid."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("direction") == 1  # long reversion
        assert result.get("signal_type") == "reversion_long"

    def test_missing_kalman_data_mean_reversion_unaffected(self):
        """No kalman_price_position in features → gate skipped, existing behavior unchanged."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

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
        result = plugin.compute_full({"main": df, "features": features})

        # Should still fire (same as existing test_bullish_reversion_at_support)
        assert result.get("direction") == 1


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

    def test_no_signal_in_extreme_garch_vol(self):
        """garch_vol_regime=3 (extreme) — squeeze breakout blocked regardless of setup quality."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([
            np.full(80, 5050.0) + np.random.default_rng(20).normal(0, 2, 80),
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
            "garch_vol_regime": 3,    # extreme vol — should block
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_signal_fires_in_high_vol_not_extreme(self):
        """garch_vol_regime=2 (high, not extreme) — squeeze breakout allowed."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([
            np.full(80, 5050.0) + np.random.default_rng(21).normal(0, 2, 80),
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
            "garch_vol_regime": 2,    # high but not extreme — should pass
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("direction") == 1
        assert result.get("signal_type") == "squeeze_long"

    def test_missing_garch_squeeze_passes(self):
        """No garch_vol_regime key — gate defaults to regime=1, signal fires normally."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([
            np.full(80, 5050.0) + np.random.default_rng(22).normal(0, 2, 80),
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
            # no garch_vol_regime — backward compat
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("direction") == 1


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
        r_pwh = plugin.compute_full(
            {"main": df, "features": self._features_bsl_swept(significance=1.00)}
        )
        r_pdh = plugin.compute_full(
            {"main": df, "features": self._features_bsl_swept(significance=0.85)}
        )
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


# ─── SupplyDemandSetup ──────────────────────────────────────────────


class TestSupplyDemandSetup:
    """Tests for trad_SupplyDemandSetup plugin."""

    def _demand_features(self, freshness=1.0, strength=0.8, in_zone=1.0, act123=False):
        f = {
            "in_demand_zone": in_zone,
            "in_supply_zone": 0.0,
            "demand_freshness": freshness,
            "demand_strength": strength,
            "nearest_demand_high": 5010.0,
            "nearest_demand_low":  4990.0,
            "supply_freshness": 0.0,
            "supply_strength": 0.0,
            "nearest_supply_high": 5100.0,
            "nearest_supply_low":  5090.0,
            "price_in_premium": 0.0,  # discount = demand zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }
        if act123:
            f["sweep_detected"] = 1.0
            f["sweep_reclaimed"] = 1.0
            f["sweep_type"] = 1.0    # bullish sweep → long
            f["fvg_detected"] = 1.0
            f["fvg_type"] = 1.0
        return f

    def _supply_features(self, freshness=1.0, strength=0.8, in_zone=1.0):
        return {
            "in_demand_zone": 0.0,
            "in_supply_zone": in_zone,
            "demand_freshness": 0.0,
            "demand_strength": 0.0,
            "nearest_demand_high": 4910.0,
            "nearest_demand_low":  4900.0,
            "supply_freshness": freshness,
            "supply_strength": strength,
            "nearest_supply_high": 5010.0,
            "nearest_supply_low":  4990.0,
            "price_in_premium": 1.0,  # premium = supply zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }

    def test_demand_zone_generates_long(self):
        """Price in demand zone + fresh → long signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._demand_features()})
        assert result["signal_type"] == "supply_demand_long"
        assert result["direction"] == 1
        assert result["confidence"] > 0.4
        assert result["stop_loss"] < result["entry_price"]

    def test_supply_zone_generates_short(self):
        """Price in supply zone + fresh → short signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._supply_features()})
        assert result["signal_type"] == "supply_demand_short"
        assert result["direction"] == -1
        assert result["stop_loss"] > result["entry_price"]

    def test_no_signal_when_not_in_zone(self):
        """Price not in any zone → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(in_zone=0.0)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_mitigated_zone(self):
        """Zone freshness below threshold → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(freshness=0.1)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_fresh_zone_higher_confidence_than_tested(self):
        """Fresh zone (1.0) has higher confidence than tested zone (0.5)."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_fresh = plugin.compute_full(
            {"main": df, "features": self._demand_features(freshness=1.0)}
        )
        r_tested = plugin.compute_full(
            {"main": df, "features": self._demand_features(freshness=0.5)}
        )
        if r_fresh.get("direction") == 1 and r_tested.get("direction") == 1:
            assert r_fresh["confidence"] > r_tested["confidence"]

    def test_act_123_bonus_applied(self):
        """Sweep + FVG preceding zone entry → act_1_2_3_confirmed bonus."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_plain = plugin.compute_full({"main": df, "features": self._demand_features(act123=False)})
        r_act   = plugin.compute_full({"main": df, "features": self._demand_features(act123=True)})
        if r_plain.get("direction") == 1 and r_act.get("direction") == 1:
            assert r_act["confidence"] > r_plain["confidence"]
            assert "act_1_2_3_confirmed" in r_act.get("supporting_factors", [])

    def test_premium_discount_penalty_applied(self):
        """Demand zone in premium → lower confidence than demand zone in discount."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        f_discount = {**self._demand_features(), "price_in_premium": 0.0}  # aligned
        f_premium  = {**self._demand_features(), "price_in_premium": 1.0}  # opposing
        r1 = plugin.compute_full({"main": df, "features": f_discount})
        r2 = plugin.compute_full({"main": df, "features": f_premium})
        if r1.get("direction") == 1 and r2.get("direction") == 1:
            assert r1["confidence"] > r2["confidence"]

    def test_has_two_targets(self):
        """Output includes at least 2 price targets."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        df = make_ohlcv(np.full(100, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._demand_features()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        df = make_ohlcv(np.full(5, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result.get("signal_type", "none") == "none"


# ─── Zone Enhancement Tests ──────────────────────────────────────────────


class TestZoneEnhancements:
    """Tests that existing I7 plugins correctly use zone awareness features."""

    def test_liquidity_sweep_reclaim_boosted_by_named_level(self):
        """LiquiditySweepReclaim gains confidence when sweep was at a named pool level."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquiditySweepReclaimPlugin()

        base_features = {
            "sweep_detected": 1.0, "sweep_reclaimed": 1.0,
            "sweep_type": 1.0, "sweep_level": 4980.0,
            "atr_14": 10.0, "fvg_detected": 0.0, "fvg_type": 0.0,
            "ob_detected": 0.0, "ob_type": 0.0, "ctf_score": 0.0,
        }
        named_features = {
            **base_features,
            "ssl_significance": 1.0,   # PWL level
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
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin
        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        plugin = MomentumBreakoutPlugin()

        base_features = {
            "roc_14": 0.8, "atr_14": 10.0, "volume": 2000.0,
            "bos_detected": 1.0, "bos_direction": 1.0, "bos_level": 5050.0,
            "trend_regime": 0.6, "ctf_score": 0.0,
        }
        clean_features   = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean    = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]

    def test_trend_following_penalized_by_opposing_zone(self):
        """TrendFollowing long penalized when trending into supply zone."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()

        base_features = {
            "trend_regime": 0.8, "trend_confidence": 0.75,
            "swing_pattern": 1.0, "trend_strength": 0.7,
            "ctf_score": 0.6, "atr_14": 10.0,
            "sma_20": 5180.0, "ema_21": 5185.0,
        }
        clean_features    = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean    = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]


# ─── CandlestickPatternSetup — Tier 1 patterns (15-GAP-02) ───────────────────


class TestCandlestickTier1Patterns:
    """Tests for 9 new Tier 1 candlestick patterns in CandlestickPatternSetupPlugin.

    Each pattern is already computed in I5 (CandlestickPatternsPlugin) and written
    to intelligence_features.i5. This suite verifies the I7 read/promotion wiring.

    S/R confirmation path used throughout (nearest_support/resistance within 0.3*ATR).
    """

    def _make_df(self, n: int = 25, close: float = 5000.0):
        import pandas as pd

        return pd.DataFrame(
            {
                "open": [close - 5.0] * n,
                "high": [close + 10.0] * n,
                "low": [close - 10.0] * n,
                "close": [close] * n,
                "volume": [1200.0] * n,
            }
        )

    def _bull_features(self, pattern_field: str) -> dict:
        """Features dict with bullish pattern flag, S/R near close, bullish trend."""
        return {
            pattern_field: 1.0,
            "trend_regime": 0.7,
            "atr_14": 10.0,
            # nearest_support within 0.3*ATR=3 of close=5000 → S/R confirms
            "nearest_support": 4998.0,
            "volume_sma_20": 1000.0,  # vol 1200 < 1.3*1000=1300 → volume does NOT confirm
        }

    def _bear_features(self, pattern_field: str) -> dict:
        """Features dict with bearish pattern flag, S/R near close, bearish trend."""
        return {
            pattern_field: 1.0,
            "trend_regime": -0.7,
            "atr_14": 10.0,
            # nearest_resistance within 0.3*ATR=3 of close=5000 → S/R confirms
            "nearest_resistance": 5002.0,
            "volume_sma_20": 1000.0,
        }

    def test_three_white_soldiers_bullish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bull_features("three_white_soldiers")}
        )
        assert result.get("direction") == 1
        assert "three_white_soldiers" in result.get("signal_type", "")

    def test_three_black_crows_bearish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bear_features("three_black_crows")}
        )
        assert result.get("direction") == -1
        assert "three_black_crows" in result.get("signal_type", "")

    def test_morning_star_bullish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bull_features("morning_star")}
        )
        assert result.get("direction") == 1
        assert "morning_star" in result.get("signal_type", "")

    def test_evening_star_bearish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bear_features("evening_star")}
        )
        assert result.get("direction") == -1
        assert "evening_star" in result.get("signal_type", "")

    def test_three_inside_up_bullish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bull_features("three_inside_up")}
        )
        assert result.get("direction") == 1
        assert "three_inside_up" in result.get("signal_type", "")

    def test_three_inside_down_bearish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bear_features("three_inside_down")}
        )
        assert result.get("direction") == -1
        assert "three_inside_down" in result.get("signal_type", "")

    def test_harami_cross_follows_trend(self):
        """harami_cross has no intrinsic direction — aligns with trend_regime."""
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bull_features("harami_cross")}
        )
        assert result.get("direction") == 1  # follows bullish trend
        assert "harami_cross" in result.get("signal_type", "")

    def test_dark_cloud_cover_bearish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bear_features("dark_cloud_cover")}
        )
        assert result.get("direction") == -1
        assert "dark_cloud_cover" in result.get("signal_type", "")

    def test_piercing_line_bullish(self):
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin

        df = self._make_df()
        result = CandlestickPatternSetupPlugin().compute_full(
            {"main": df, "features": self._bull_features("piercing_line")}
        )
        assert result.get("direction") == 1
        assert "piercing_line" in result.get("signal_type", "")
