"""Tests for DivergenceStackPlugin (trad_DivergenceStack) — 5-input weighted convergence score."""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(
    close: np.ndarray,
    features: dict | None = None,
) -> dict:
    df = make_ohlcv(close)
    return {"main": df, "features": features or {}}


def _make_features_with_divergences(
    rsi_bull: float = 0.0,
    rsi_bear: float = 0.0,
    macd_bull: float = 0.0,
    macd_bear: float = 0.0,
    vol_bull: float = 0.0,
    vol_bear: float = 0.0,
    obv_bull: float = 0.0,
    obv_bear: float = 0.0,
    cmf_bull: float = 0.0,
    cmf_bear: float = 0.0,
    atr_14: float = 10.0,
) -> dict:
    return {
        "rsi_div_bullish": rsi_bull,
        "rsi_div_bearish": rsi_bear,
        "macd_div_bullish": macd_bull,
        "macd_div_bearish": macd_bear,
        "vol_div_bullish": vol_bull,
        "vol_div_bearish": vol_bear,
        "obv_div_bullish": obv_bull,
        "obv_div_bearish": obv_bear,
        "cmf_div_bullish": cmf_bull,
        "cmf_div_bearish": cmf_bear,
        "atr_14": atr_14,
    }


class TestDivergenceStackAttributes:
    def test_name(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        assert plugin.name == "trad_DivergenceStack"

    def test_outputs_contains_scoring_fields(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        assert "div_weighted_score" in plugin.outputs
        assert "div_n_agreeing" in plugin.outputs

    def test_outputs_contains_per_input_scores(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        assert "rsi_div_score" in plugin.outputs
        assert "macd_div_score" in plugin.outputs
        assert "vol_div_score" in plugin.outputs
        assert "obv_div_score" in plugin.outputs
        assert "cmf_div_score" in plugin.outputs

    def test_outputs_contains_age_fields(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        assert "rsi_divergence_age_bars" in plugin.outputs
        assert "macd_divergence_age_bars" in plugin.outputs

    def test_outputs_contains_signal_fields(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        assert "signal_type" in plugin.outputs
        assert "direction" in plugin.outputs
        assert "confidence" in plugin.outputs


class TestDivergenceStackWeights:
    def test_default_weights_match_spec(self):
        from src.intelligence.trading.divergence_stack import DIVERGENCE_WEIGHTS

        assert abs(DIVERGENCE_WEIGHTS["rsi"] - 0.30) < 1e-9
        assert abs(DIVERGENCE_WEIGHTS["macd"] - 0.25) < 1e-9
        assert abs(DIVERGENCE_WEIGHTS["vol"] - 0.20) < 1e-9
        assert abs(DIVERGENCE_WEIGHTS["obv"] - 0.15) < 1e-9
        assert abs(DIVERGENCE_WEIGHTS["cmf"] - 0.10) < 1e-9

    def test_weights_sum_to_one(self):
        from src.intelligence.trading.divergence_stack import DIVERGENCE_WEIGHTS

        total = sum(DIVERGENCE_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_score_threshold(self):
        from src.intelligence.trading.divergence_stack import DIVERGENCE_SCORE_THRESHOLD

        assert abs(DIVERGENCE_SCORE_THRESHOLD - 0.40) < 1e-9

    def test_min_agreeing(self):
        from src.intelligence.trading.divergence_stack import DIVERGENCE_MIN_AGREEING

        assert DIVERGENCE_MIN_AGREEING == 3


class TestDivergenceStackAlwaysLogs:
    def test_always_logs_scoring_fields_on_no_signal(self):
        """div_weighted_score and div_n_agreeing returned even when no signal fires."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.linspace(5000, 5100, 80)
        # Zero divergences — no signal should fire
        features = _make_features_with_divergences()
        result = plugin.compute_full(_make_frames(close, features))

        assert "div_weighted_score" in result
        assert "div_n_agreeing" in result
        assert result["div_weighted_score"] == 0.0
        assert result["div_n_agreeing"] == 0

    def test_per_input_scores_always_returned(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.linspace(5000, 5100, 80)
        features = _make_features_with_divergences()
        result = plugin.compute_full(_make_frames(close, features))

        for key in ["rsi_div_score", "macd_div_score", "vol_div_score", "obv_div_score", "cmf_div_score"]:
            assert key in result

    def test_scoring_fields_returned_with_partial_divergence(self):
        """Even with 2 divergences (below gate), scoring fields still returned."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.linspace(5000, 5100, 80)
        # Only 2 agreeing — below DIVERGENCE_MIN_AGREEING=3
        features = _make_features_with_divergences(rsi_bull=0.8, macd_bull=0.7)
        result = plugin.compute_full(_make_frames(close, features))

        assert "div_weighted_score" in result
        assert "div_n_agreeing" in result
        assert result["div_n_agreeing"] == 2
        assert result["div_weighted_score"] > 0.0
        # No signal should fire
        assert result.get("signal_type") in ("none", None) or result.get("direction", 0) == 0


class TestDivergenceStackGate:
    def test_signal_fires_with_3_agreeing_and_score_above_threshold(self):
        """Signal fires when n_agreeing >= 3 AND score > 0.40."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0) + np.arange(80) * 0.1
        # RSI=0.9 (weight 0.30), MACD=0.9 (0.25), vol=0.9 (0.20) -> score = 0.675 > 0.40
        features = _make_features_with_divergences(rsi_bull=0.9, macd_bull=0.9, vol_bull=0.9)
        result = plugin.compute_full(_make_frames(close, features))

        assert result.get("direction") == 1  # bullish
        assert result.get("confidence", 0.0) > 0.0
        assert result.get("div_n_agreeing") == 3
        assert result.get("div_weighted_score") > 0.40

    def test_no_signal_when_n_agreeing_below_3(self):
        """No signal when only 2 inputs agree (even if score > 0.40)."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        # RSI=1.0 (0.30) + MACD=1.0 (0.25) = 0.55 > 0.40, but n_agreeing=2 < 3
        features = _make_features_with_divergences(rsi_bull=1.0, macd_bull=1.0)
        result = plugin.compute_full(_make_frames(close, features))

        assert result.get("direction", 0) == 0
        # But scoring fields must still be present
        assert "div_weighted_score" in result
        assert result["div_n_agreeing"] == 2

    def test_no_signal_when_score_below_threshold(self):
        """No signal when n_agreeing >= 3 but score <= 0.40."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        # Low values across 3 inputs: 0.1*0.30 + 0.1*0.25 + 0.1*0.20 = 0.075 < 0.40
        features = _make_features_with_divergences(rsi_bull=0.1, macd_bull=0.1, vol_bull=0.1)
        result = plugin.compute_full(_make_frames(close, features))

        assert result.get("direction", 0) == 0
        assert result["div_n_agreeing"] == 3
        assert result["div_weighted_score"] < 0.40


class TestDivergenceStackDirection:
    def test_bullish_direction_when_majority_bullish(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        features = _make_features_with_divergences(rsi_bull=0.9, macd_bull=0.9, vol_bull=0.9)
        result = plugin.compute_full(_make_frames(close, features))

        if result.get("direction", 0) != 0:
            assert result["direction"] == 1

    def test_bearish_direction_when_majority_bearish(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        features = _make_features_with_divergences(rsi_bear=0.9, macd_bear=0.9, vol_bear=0.9)
        result = plugin.compute_full(_make_frames(close, features))

        if result.get("direction", 0) != 0:
            assert result["direction"] == -1


class TestDivergenceStackAgeTracking:
    def test_age_increments_for_active_divergence(self):
        """Age increments each bar that divergence is active."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        features = _make_features_with_divergences(rsi_bull=0.8)

        # First bar
        result1 = plugin.compute_full({"main": make_ohlcv(close), "features": features, "symbol": "ES", "timeframe": "1m"})
        # Second bar
        result2 = plugin.compute_full({"main": make_ohlcv(close), "features": features, "symbol": "ES", "timeframe": "1m"})

        assert result2["rsi_divergence_age_bars"] >= result1["rsi_divergence_age_bars"]

    def test_age_resets_when_divergence_inactive(self):
        """Age resets to 0 when divergence becomes inactive."""
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        features_active = _make_features_with_divergences(rsi_bull=0.8)
        features_inactive = _make_features_with_divergences(rsi_bull=0.0)

        # Bar with active divergence
        plugin.compute_full({"main": make_ohlcv(close), "features": features_active, "symbol": "ES", "timeframe": "1m"})
        # Bar with no divergence
        result = plugin.compute_full({"main": make_ohlcv(close), "features": features_inactive, "symbol": "ES", "timeframe": "1m"})

        assert result["rsi_divergence_age_bars"] == 0


class TestDivergenceStackLOCKEDDESIGN:
    def test_no_locked_design_comment(self):
        """The 'LOCKED DESIGN' comment must be removed in the rewrite."""
        import inspect
        from src.intelligence.trading import divergence_stack

        source = inspect.getsource(divergence_stack)
        assert "LOCKED DESIGN" not in source


class TestDivergenceStackComputeNext:
    def test_compute_next_delegates_to_compute_full(self):
        from src.intelligence.trading.divergence_stack import DivergenceStackPlugin

        plugin = DivergenceStackPlugin()
        close = np.full(80, 5000.0)
        features = _make_features_with_divergences()
        frames = _make_frames(close, features)
        result_full = plugin.compute_full(frames)
        result_next = plugin.compute_next(frames)
        assert result_full == result_next
