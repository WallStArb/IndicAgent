"""Tests for trad_MomentumBreakout setup plugin."""

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _base_features(roc=0.5, swing_high=5010.0, swing_low=4990.0, trend_regime=0.0):
    """Minimal features for a passing triple-gate setup."""
    return {
        "roc_14": roc,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "trend_regime": trend_regime,
        "atr_14": 8.0,
        "hmm_prob_trending_up": 0.70,  # continuous regime gate (>= 0.30)
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
    }


class TestMomentumBreakout:
    def test_long_breakout_all_gates_pass(self):
        """ROC spike up + volume expansion + price above swing_high → momentum_breakout_long."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5010.0)
        close[-1] = 5015.0  # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0  # 2x average → passes 1.5x gate
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
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

        assert result.get("signal_type") == "momentum_breakout_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price") == pytest.approx(5010.0, abs=1.0)  # at_limit = swing_high
        assert result.get("stop_loss") < result["entry_price"]
        assert len(result.get("targets", [])) >= 2

    def test_short_breakout_all_gates_pass(self):
        """ROC spike down + volume expansion + price below swing_low → momentum_breakout_short."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 4990.0)
        close[-1] = 4985.0  # below swing_low=4990
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=-0.5, swing_low=4990.0)

        plugin = MomentumBreakoutPlugin()
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

        assert result.get("signal_type") == "momentum_breakout_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss") > result["entry_price"]

    def test_no_signal_roc_too_weak(self):
        """ROC below threshold → no signal even if volume and structure qualify."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5015.0)
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.1, swing_high=5010.0)  # 0.1 < 0.3 threshold

        plugin = MomentumBreakoutPlugin()
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

    def test_no_signal_low_volume(self):
        """ROC spike + structure break but volume below 1.5x → no signal."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5015.0)  # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 1200.0  # only 1.2x — below 1.5x threshold
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
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

    def test_no_signal_no_structure_break(self):
        """Strong ROC + volume but price hasn't cleared swing_high → no signal."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5005.0)  # below swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
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

    def test_no_signal_roc_direction_mismatch(self):
        """Positive ROC but only swing_low broken (not swing_high) → no signal."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5005.0)  # above swing_low=4990 but below swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        # Positive ROC — only tries long gate. price=5005 < swing_high=5010 → no break.
        features = _base_features(roc=0.5, swing_high=5010.0, swing_low=4990.0)

        plugin = MomentumBreakoutPlugin()
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

    def test_inline_roc_fallback_when_feature_absent(self):
        """Plugin computes ROC from df if roc_14 not in features (fallback path)."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        # Build 50-bar series where roc_14 is large enough to trigger
        close = np.full(50, 5000.0)
        close[-15:] = np.linspace(5000.0, 5025.0, 15)  # ~0.5% rise over 14 bars
        close[-1] = 5025.0  # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        # Note: no roc_14 key — plugin must compute inline
        features = {
            "swing_high": 5010.0,
            "swing_low": 4990.0,
            "trend_regime": 0.0,
            "atr_14": 8.0,
            "hmm_prob_trending_up": 0.70,
            "hmm_prob_trending_down": 0.10,
            "ctf_score": 0.40,
        }

        plugin = MomentumBreakoutPlugin()
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

        assert result.get("signal_type") == "momentum_breakout_long"

    def test_confidence_scales_with_roc_magnitude(self):
        """Larger ROC spike → higher confidence, all else equal."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        plugin = MomentumBreakoutPlugin()
        close = np.full(50, 5015.0)
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)

        r_small = plugin.compute_full(
            {
                "main": df,
                "i1": _base_features(roc=0.35, swing_high=5010.0),
                "i2": _base_features(roc=0.35, swing_high=5010.0),
                "i3": _base_features(roc=0.35, swing_high=5010.0),
                "i4": _base_features(roc=0.35, swing_high=5010.0),
                "i5": _base_features(roc=0.35, swing_high=5010.0),
                "smc": _base_features(roc=0.35, swing_high=5010.0),
                "i6": _base_features(roc=0.35, swing_high=5010.0),
            }
        )
        r_large = plugin.compute_full(
            {
                "main": df,
                "i1": _base_features(roc=1.0, swing_high=5010.0),
                "i2": _base_features(roc=1.0, swing_high=5010.0),
                "i3": _base_features(roc=1.0, swing_high=5010.0),
                "i4": _base_features(roc=1.0, swing_high=5010.0),
                "i5": _base_features(roc=1.0, swing_high=5010.0),
                "smc": _base_features(roc=1.0, swing_high=5010.0),
                "i6": _base_features(roc=1.0, swing_high=5010.0),
            }
        )

        assert r_small.get("signal_type") == "momentum_breakout_long"
        assert r_large.get("signal_type") == "momentum_breakout_long"
        assert r_large["confidence"] > r_small["confidence"]

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty dict."""
        from src.intelligence.archive.trading_i7.momentum_breakout import MomentumBreakoutPlugin

        close = np.array([5000.0, 5005.0, 5010.0])
        df = make_ohlcv(close)
        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {} or result.get("signal_type", "none") == "none"
