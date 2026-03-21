"""TDD tests for the 5 new CIS evidence-contributor I7 plugins.

Covers RED→GREEN cycle for:
  - CHoCHReversalPlugin (trad_CHoCHReversal)
  - FVGFillPlugin (trad_FVGFill)
  - PatternCompletionPlugin (trad_PatternCompletion)
  - DivergenceStackPlugin (trad_DivergenceStack)
  - RegimeTransitionPlugin (trad_RegimeTransition)
"""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frames(n: int = 30, close_val: float = 5000.0, features: dict | None = None) -> dict:
    """Build frames dict with n-bar OHLCV and optional features overlay."""
    close = np.full(n, close_val, dtype=float)
    df = make_ohlcv(close)
    return {"main": df, "features": features or {}}


def _frames_short(n: int = 5) -> dict:
    """Build an under-minimum-lookback frames dict."""
    close = np.full(n, 5000.0, dtype=float)
    df = make_ohlcv(close)
    return {"main": df, "features": {}}


# ---------------------------------------------------------------------------
# TestCHoCHReversal
# ---------------------------------------------------------------------------


class TestCHoCHReversal:
    """Tests for trad_CHoCHReversal plugin."""

    def _plugin(self):
        from src.intelligence.trading.choch_reversal import CHoCHReversalPlugin

        return CHoCHReversalPlugin()

    def test_bullish_choch_fires_long(self):
        """choch_detected=1.0, choch_direction=1 → direction==1."""
        plugin = self._plugin()
        features = {
            "choch_detected": 1.0,
            "choch_direction": 1,
            "hmm_regime": 1.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1
        assert result.get("confidence", 0.0) > 0.0
        assert result.get("signal_type") not in (None, "none")

    def test_bearish_choch_fires_short(self):
        """choch_detected=1.0, choch_direction=-1 → direction==-1."""
        plugin = self._plugin()
        features = {
            "choch_detected": 1.0,
            "choch_direction": -1,
            "hmm_regime": 2.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1
        assert result.get("confidence", 0.0) > 0.0

    def test_no_choch_no_signal(self):
        """choch_detected=0.0 → direction==0 (no signal)."""
        plugin = self._plugin()
        features = {
            "choch_detected": 0.0,
            "choch_direction": 1,
            "hmm_regime": 1.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_insufficient_data_returns_empty_or_no_signal(self):
        """Too few bars → returns empty dict or signal_type=='none'."""
        plugin = self._plugin()
        result = plugin.compute_full(_frames_short())
        # Acceptable: empty dict OR _no_signal() structure with direction==0
        if result:
            assert result.get("direction") == 0 or result.get("signal_type") == "none"

    def test_has_module_level_singleton(self):
        """Plugin module must export a module-level `plugin` singleton."""
        from src.intelligence.trading.choch_reversal import plugin

        assert plugin is not None
        assert plugin.name == "trad_CHoCHReversal"


# ---------------------------------------------------------------------------
# TestFVGFill
# ---------------------------------------------------------------------------


class TestFVGFill:
    """Tests for trad_FVGFill plugin."""

    def _plugin(self):
        from src.intelligence.trading.fvg_fill import FVGFillPlugin

        return FVGFillPlugin()

    def test_bullish_fvg_fires_long(self):
        """fvg_type=1, fvg_open_count>=1 → direction==1."""
        plugin = self._plugin()
        features = {
            "fvg_type": 1,
            "fvg_open_count": 2.0,
            "fvg_top": 5010.0,
            "fvg_bottom": 5000.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1
        assert result.get("confidence", 0.0) > 0.0
        assert result.get("signal_type") not in (None, "none")

    def test_bearish_fvg_fires_short(self):
        """fvg_type=-1, fvg_open_count>=1 → direction==-1."""
        plugin = self._plugin()
        features = {
            "fvg_type": -1,
            "fvg_open_count": 1.0,
            "fvg_top": 5010.0,
            "fvg_bottom": 4990.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1
        assert result.get("confidence", 0.0) > 0.0

    def test_no_fvg_no_signal(self):
        """fvg_type=0 → direction==0 (no signal)."""
        plugin = self._plugin()
        features = {
            "fvg_type": 0,
            "fvg_open_count": 0.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_fvg_open_count_zero_no_signal(self):
        """fvg_type=1 but fvg_open_count=0.0 → no signal."""
        plugin = self._plugin()
        features = {
            "fvg_type": 1,
            "fvg_open_count": 0.0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_confidence_scales_with_open_count(self):
        """More open FVGs → higher confidence."""
        plugin = self._plugin()
        feat_low = {
            "fvg_type": 1,
            "fvg_open_count": 1.0,
            "fvg_top": 5010.0,
            "fvg_bottom": 5000.0,
            "atr_14": 10.0,
        }
        feat_high = {
            "fvg_type": 1,
            "fvg_open_count": 3.0,
            "fvg_top": 5010.0,
            "fvg_bottom": 5000.0,
            "atr_14": 10.0,
        }
        r_low = plugin.compute_full(_frames(features=feat_low))
        r_high = plugin.compute_full(_frames(features=feat_high))
        assert r_high.get("confidence", 0) >= r_low.get("confidence", 0)

    def test_has_module_level_singleton(self):
        """Plugin module must export a module-level `plugin` singleton."""
        from src.intelligence.trading.fvg_fill import plugin

        assert plugin is not None
        assert plugin.name == "trad_FVGFill"


# ---------------------------------------------------------------------------
# TestPatternCompletion
# ---------------------------------------------------------------------------


class TestPatternCompletion:
    """Tests for trad_PatternCompletion plugin."""

    def _plugin(self):
        from src.intelligence.trading.pattern_completion import PatternCompletionPlugin

        return PatternCompletionPlugin()

    def test_double_bottom_fires_long(self):
        """dt_db_pattern=2 (double bottom), dt_db_confidence>0.5 → direction==1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.75,
            "dt_db_pattern": 2,  # double_bottom
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1
        assert result.get("confidence", 0.0) > 0.0

    def test_double_top_fires_short(self):
        """dt_db_pattern=1 (double top), dt_db_confidence>0.5 → direction==-1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.80,
            "dt_db_pattern": 1,  # double_top
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1

    def test_hs_top_fires_short(self):
        """hs_pattern=1 (HS top), hs_confidence>0.5 → direction==-1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.0,
            "dt_db_pattern": 0,
            "hs_confidence": 0.72,
            "hs_pattern": 1,  # hs_top
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1

    def test_hs_bottom_fires_long(self):
        """hs_pattern=2 (inverted HS), hs_confidence>0.5 → direction==1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.0,
            "dt_db_pattern": 0,
            "hs_confidence": 0.65,
            "hs_pattern": 2,  # hs_bottom (inverted)
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1

    def test_triangle_bullish_fires_long(self):
        """tri_confidence>0.5, tri_breakout_bias=1 → direction==1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.0,
            "dt_db_pattern": 0,
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.68,
            "tri_breakout_bias": 1,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1

    def test_triangle_bearish_fires_short(self):
        """tri_confidence>0.5, tri_breakout_bias=-1 → direction==-1."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.0,
            "dt_db_pattern": 0,
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.70,
            "tri_breakout_bias": -1,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1

    def test_no_pattern_no_signal(self):
        """All confidences=0.0 → direction==0 (no signal)."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.0,
            "dt_db_pattern": 0,
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_low_confidence_below_threshold_no_signal(self):
        """dt_db_confidence=0.3 (below 0.5 threshold) → direction==0."""
        plugin = self._plugin()
        features = {
            "dt_db_confidence": 0.3,
            "dt_db_pattern": 2,
            "hs_confidence": 0.0,
            "hs_pattern": 0,
            "tri_confidence": 0.0,
            "tri_breakout_bias": 0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_has_module_level_singleton(self):
        """Plugin module must export a module-level `plugin` singleton."""
        from src.intelligence.trading.pattern_completion import plugin

        assert plugin is not None
        assert plugin.name == "trad_PatternCompletion"


# ---------------------------------------------------------------------------
# TestDivergenceStack
# ---------------------------------------------------------------------------


class TestDivergenceStack:
    """Tests for trad_DivergenceStack plugin — 5-input weighted convergence score."""

    def _plugin(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        return DivergenceStackPlugin()

    def test_dual_bullish_fires_long(self):
        """RSI + MACD + vol bullish (n_agreeing=3, score=0.675 > 0.40) → direction==1."""
        plugin = self._plugin()
        features = {
            "rsi_div_bullish": 0.9,
            "macd_div_bullish": 0.9,
            "vol_div_bullish": 0.9,
            "rsi_div_bearish": 0.0,
            "macd_div_bearish": 0.0,
            "vol_div_bearish": 0.0,
            "atr_14": 10.0,
            "swing_low": 4980.0,
            "sr_nearest_support": 4970.0,
            "sr_nearest_resistance": 5030.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1
        assert result.get("confidence", 0.0) > 0.0

    def test_dual_bearish_fires_short(self):
        """RSI + MACD + vol bearish (n_agreeing=3, score > 0.40) → direction==-1."""
        plugin = self._plugin()
        features = {
            "rsi_div_bullish": 0.0,
            "macd_div_bullish": 0.0,
            "vol_div_bullish": 0.0,
            "rsi_div_bearish": 0.9,
            "macd_div_bearish": 0.9,
            "vol_div_bearish": 0.9,
            "atr_14": 10.0,
            "swing_high": 5020.0,
            "sr_nearest_support": 4970.0,
            "sr_nearest_resistance": 5030.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1

    def test_single_rsi_only_no_signal(self):
        """Only RSI bullish divergence (vol below threshold) → direction==0."""
        plugin = self._plugin()
        features = {
            "rsi_div_bullish": 0.7,
            "vol_div_bullish": 0.1,  # below 0.3 threshold
            "rsi_div_bearish": 0.0,
            "vol_div_bearish": 0.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_single_volume_only_no_signal(self):
        """Only volume bullish divergence (RSI below threshold) → direction==0."""
        plugin = self._plugin()
        features = {
            "rsi_div_bullish": 0.1,  # below 0.3 threshold
            "vol_div_bullish": 0.7,
            "rsi_div_bearish": 0.0,
            "vol_div_bearish": 0.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_insufficient_data_returns_empty_or_no_signal(self):
        """Too few bars → returns empty dict or direction==0."""
        plugin = self._plugin()
        result = plugin.compute_full(_frames_short())
        if result:
            assert result.get("direction") == 0

    def test_confidence_formula(self):
        """Verify confidence uses compose_confidence(weighted_score / 0.60) with [0.10, 0.95] contract.

        With RSI=0.9 (0.30), MACD=0.9 (0.25), vol=0.9 (0.20) — 3 agreeing, score=0.675.
        Raw = 0.675 / 0.60 = 1.125, clamped to CONF_CEIL=0.95.
        """
        from src.intelligence.trading.confidence_utils import CONF_CEIL, CONF_FLOOR, compose_confidence
        from src.intelligence.trading.divergence_stack import DIVERGENCE_WEIGHTS

        plugin = self._plugin()
        rsi_val, macd_val, vol_val = 0.9, 0.9, 0.9
        features = {
            "rsi_div_bullish": rsi_val,
            "macd_div_bullish": macd_val,
            "vol_div_bullish": vol_val,
            "rsi_div_bearish": 0.0,
            "macd_div_bearish": 0.0,
            "vol_div_bearish": 0.0,
            "atr_14": 10.0,
            "swing_low": 4980.0,
            "sr_nearest_support": 4970.0,
            "sr_nearest_resistance": 5030.0,
        }
        result = plugin.compute_full(_frames(features=features))
        weighted_score = (
            DIVERGENCE_WEIGHTS["rsi"] * rsi_val
            + DIVERGENCE_WEIGHTS["macd"] * macd_val
            + DIVERGENCE_WEIGHTS["vol"] * vol_val
        )
        expected = compose_confidence(weighted_score / 0.60)
        if result.get("direction", 0) != 0:
            assert abs(result.get("confidence", 0.0) - expected) < 1e-4
            assert result["confidence"] >= CONF_FLOOR
            assert result["confidence"] <= CONF_CEIL

    def test_has_module_level_singleton(self):
        """Plugin module must export a module-level `plugin` singleton."""
        from src.intelligence.trading.divergence_stack import plugin

        assert plugin is not None
        assert plugin.name == "trad_DivergenceStack"


# ---------------------------------------------------------------------------
# TestRegimeTransition
# ---------------------------------------------------------------------------


class TestRegimeTransition:
    """Tests for trad_RegimeTransition plugin."""

    def _plugin(self):
        from src.intelligence.trading.regime_transition import RegimeTransitionPlugin

        return RegimeTransitionPlugin()

    def test_bullish_transition_fires_long(self):
        """cp_probability>0.5, choch_direction=1, hmm toward trend_up → direction==1."""
        plugin = self._plugin()
        features = {
            "cp_probability": 0.75,
            "choch_detected": 1.0,
            "choch_direction": 1,
            "hmm_regime": 1.0,
            "hmm_prob_trending_up": 0.8,
            "hmm_prob_trending_down": 0.1,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 1
        assert result.get("confidence", 0.0) > 0.0

    def test_bearish_transition_fires_short(self):
        """cp_probability>0.5, choch_detected, choch_direction=-1, hmm toward trend_down → -1."""
        plugin = self._plugin()
        features = {
            "cp_probability": 0.80,
            "choch_detected": 1.0,
            "choch_direction": -1,
            "hmm_regime": 2.0,
            "hmm_prob_trending_up": 0.1,
            "hmm_prob_trending_down": 0.8,
            "atr_14": 10.0,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == -1

    def test_low_cp_probability_no_signal(self):
        """cp_probability<0.5 → direction==0 (changepoint gate fails)."""
        plugin = self._plugin()
        features = {
            "cp_probability": 0.3,  # below 0.5 threshold
            "choch_detected": 1.0,
            "choch_direction": 1,
            "hmm_regime": 1.0,
            "hmm_prob_trending_up": 0.7,
            "hmm_prob_trending_down": 0.2,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_no_choch_no_signal(self):
        """choch_detected=0.0 → direction==0 even if cp_probability is high."""
        plugin = self._plugin()
        features = {
            "cp_probability": 0.80,
            "choch_detected": 0.0,  # gate fails
            "choch_direction": 1,
            "hmm_regime": 1.0,
            "hmm_prob_trending_up": 0.8,
            "hmm_prob_trending_down": 0.1,
        }
        result = plugin.compute_full(_frames(features=features))
        assert result.get("direction") == 0

    def test_has_module_level_singleton(self):
        """Plugin module must export a module-level `plugin` singleton."""
        from src.intelligence.trading.regime_transition import plugin

        assert plugin is not None
        assert plugin.name == "trad_RegimeTransition"
