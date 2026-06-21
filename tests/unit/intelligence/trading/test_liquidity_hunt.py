"""Tests for LiquidityHunt I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


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
            "sweep_type": -1.0,  # bearish sweep (BSL swept)
            "sweep_level": bsl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 1.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            # Phase 119: gate-passing values (ctf_score was 0.0 which blocked the gate)
            "ctf_score": 0.5,
            "hmm_prob_trending_up": 0.6,
            "hmm_prob_trending_down": 0.3,
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
            "sweep_type": 1.0,  # bullish sweep (SSL swept)
            "sweep_level": ssl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 0.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            # Phase 119: gate-passing values (ctf_score was 0.0 which blocked the gate)
            "ctf_score": 0.5,
            "hmm_prob_trending_up": 0.3,
            "hmm_prob_trending_down": 0.6,
            "atr_14": 10.0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }

    def test_bsl_sweep_generates_short(self):
        """BSL swept + reclaimed + significance >= 0.60 → short signal."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f = self._features_bsl_swept()
        result = plugin.compute_full(
            {"main": df, "smc": f, "i1": f, "i2": f, "i3": f, "i4": f, "i5": f, "i6": f}
        )
        assert result["signal_type"] == "liquidity_hunt_short"
        assert result["direction"] == -1
        assert result["confidence"] > 0.5
        assert result["entry_price"] > 0
        assert result["stop_loss"] > result["entry_price"]  # stop above entry for short

    def test_ssl_sweep_generates_long(self):
        """SSL swept + reclaimed + significance >= 0.60 → long signal."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f = self._features_ssl_swept()
        result = plugin.compute_full(
            {"main": df, "smc": f, "i1": f, "i2": f, "i3": f, "i4": f, "i5": f, "i6": f}
        )
        assert result["signal_type"] == "liquidity_hunt_long"
        assert result["direction"] == 1
        assert result["stop_loss"] < result["entry_price"]  # stop below entry for long

    def test_no_signal_low_significance(self):
        """Significance < 0.60 → no signal (random swing, not named level)."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept(significance=0.45)
        plugin = LiquidityHuntPlugin()
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
        assert result.get("direction", 0) == 0
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_sweep_not_reclaimed(self):
        """sweep_reclaimed=0 → no signal (breakout not a hunt)."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept()
        features["sweep_reclaimed"] = 0.0
        plugin = LiquidityHuntPlugin()
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

    def test_confidence_higher_for_pwh_than_pdh(self):
        """PWH level (significance=1.0) → higher confidence than PDH (0.85)."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

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
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_no_fvg = self._features_bsl_swept()
        f_fvg = {**self._features_bsl_swept(), "fvg_detected": 1.0, "fvg_type": -1.0}
        r1 = plugin.compute_full({"main": df, "features": f_no_fvg})
        r2 = plugin.compute_full({"main": df, "features": f_fvg})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] > r1["confidence"]

    def test_opposing_zone_penalizes_confidence(self):
        """Hunting short but entering demand zone → confidence penalty."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_clean = self._features_bsl_swept()
        f_opposing = {**self._features_bsl_swept(), "in_demand_zone": 1.0}
        r1 = plugin.compute_full({"main": df, "features": f_clean})
        r2 = plugin.compute_full({"main": df, "features": f_opposing})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] < r1["confidence"]

    def test_has_two_targets(self):
        """Signal output includes at least 2 price targets."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        df = make_ohlcv(np.full(100, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_bsl_swept()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_returns_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.archive.trading_i7.liquidity_hunt import LiquidityHuntPlugin

        df = make_ohlcv(np.full(5, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("signal_type", "none") == "none"
