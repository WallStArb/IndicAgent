"""Tests for rules-based signal aggregator."""

import pytest

from src.intelligence.trading.aggregator import (
    SETUP_PRIORITY,
    aggregate,
)


def _signal(plugin: str, direction: int, confidence: float = 0.7,
            confluence: float = 0.5, signal_type: str = "test") -> dict:
    """Build a minimal signal dict for aggregation testing."""
    return {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-02-17T14:30:00Z",
        "signal_type": signal_type,
        "setup_plugin": plugin,
        "direction": direction,
        "entry_price": 5100.0,
        "stop_loss": 5085.0 if direction == 1 else 5115.0,
        "targets": [5115.0] if direction == 1 else [5085.0],
        "confidence": confidence,
        "risk_reward_ratio": 1.0,
        "regime_context": "bullish" if direction == 1 else "bearish",
        "confluence_score": confluence,
        "supporting_factors": ["test_factor"],
        "invalidation_conditions": [],
        "ttl_bars": 10,
    }


class TestAggregateNoSignals:
    @pytest.mark.unit
    def test_empty_list_returns_no_signal(self):
        """No signals -> no_signal result."""
        result = aggregate([], trend_regime=0.5)
        assert result.selected_signal is None
        assert result.resolution_method == "no_signal"

    @pytest.mark.unit
    def test_all_none_signals_filtered(self):
        """Signals with signal_type='none' or direction=0 are filtered out."""
        none_sig = _signal("trad_TrendFollowing", 0, signal_type="none")
        result = aggregate([none_sig], trend_regime=0.5)
        assert result.selected_signal is None


class TestAggregateSoleSignal:
    @pytest.mark.unit
    def test_single_signal_selected(self):
        """One signal -> selected as sole winner."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.6)
        assert result.selected_signal is not None
        assert result.selected_signal["setup_plugin"] == "trad_TrendFollowing"
        assert result.resolution_method == "sole"
        assert result.num_signals_fired == 1
        assert result.num_agreeing == 1
        assert result.num_conflicting == 0


class TestAggregateSameDirection:
    @pytest.mark.unit
    def test_priority_wins_among_same_direction(self):
        """Multiple longs -> highest priority setup wins."""
        trend = _signal("trad_TrendFollowing", 1, confidence=0.9)
        mean_rev = _signal("trad_MeanReversion", 1, confidence=0.95)
        result = aggregate([trend, mean_rev], trend_regime=0.6)
        assert result.selected_signal["setup_plugin"] == "trad_TrendFollowing"
        assert result.resolution_method == "priority"
        assert result.num_agreeing == 2

    @pytest.mark.unit
    def test_liq_sweep_wins_over_all(self):
        """LiquiditySweepReclaim has highest priority."""
        liq = _signal("trad_LiquiditySweepReclaim", 1, confidence=0.6)
        mtf = _signal("trad_MTFAlignment", 1, confidence=0.9)
        result = aggregate([liq, mtf], trend_regime=0.6)
        assert result.selected_signal["setup_plugin"] == "trad_LiquiditySweepReclaim"

    @pytest.mark.unit
    def test_confidence_boosted_by_agreement(self):
        """Winner confidence boosted by +0.05 per agreeing signal."""
        trend = _signal("trad_TrendFollowing", 1, confidence=0.7)
        squeeze = _signal("trad_SqueezeExpansion", 1, confidence=0.6)
        result = aggregate([trend, squeeze], trend_regime=0.6)
        assert result.selected_signal["confidence"] == pytest.approx(0.75, abs=0.001)

    @pytest.mark.unit
    def test_supporting_factors_merged(self):
        """Supporting factors from all agreeing signals are merged."""
        s1 = _signal("trad_TrendFollowing", 1)
        s1["supporting_factors"] = ["strong_trend"]
        s2 = _signal("trad_SqueezeExpansion", 1)
        s2["supporting_factors"] = ["volume_expansion"]
        result = aggregate([s1, s2], trend_regime=0.6)
        factors = result.selected_signal["supporting_factors"]
        assert "strong_trend" in factors
        assert "volume_expansion" in factors


class TestAggregateMixedDirections:
    @pytest.mark.unit
    def test_majority_wins(self):
        """2 longs vs 1 short -> long side wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        l2 = _signal("trad_MTFAlignment", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, l2, s1], trend_regime=0.6)
        assert result.selected_signal["direction"] == 1
        assert result.resolution_method == "majority"
        assert result.num_conflicting == 1

    @pytest.mark.unit
    def test_tied_uses_regime_tiebreak_bullish(self):
        """1 long vs 1 short with bullish regime -> long wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=0.6)
        assert result.selected_signal["direction"] == 1
        assert result.resolution_method == "regime_tiebreak"

    @pytest.mark.unit
    def test_tied_uses_regime_tiebreak_bearish(self):
        """1 long vs 1 short with bearish regime -> short wins."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=-0.6)
        assert result.selected_signal["direction"] == -1
        assert result.resolution_method == "regime_tiebreak"

    @pytest.mark.unit
    def test_tied_ranging_emits_no_signal(self):
        """1 long vs 1 short with ranging regime -> no signal."""
        l1 = _signal("trad_TrendFollowing", 1)
        s1 = _signal("trad_MeanReversion", -1)
        result = aggregate([l1, s1], trend_regime=0.1)
        assert result.selected_signal is None
        assert result.resolution_method == "no_signal"


class TestAggregatedResultMetadata:
    @pytest.mark.unit
    def test_all_ranked_signals_returned(self):
        """all_ranked contains every signal with a composite_rank."""
        s1 = _signal("trad_TrendFollowing", 1)
        s2 = _signal("trad_SqueezeExpansion", 1)
        result = aggregate([s1, s2], trend_regime=0.6)
        assert len(result.all_ranked) == 2
        assert result.all_ranked[0]["composite_rank"] == 1
        assert result.all_ranked[1]["composite_rank"] == 2


class TestSetupPriority:
    @pytest.mark.unit
    def test_priority_order(self):
        """Priority order matches design: LiqSweep > MTF > Trend > Squeeze > MeanRev."""
        names = sorted(SETUP_PRIORITY, key=lambda k: SETUP_PRIORITY[k])
        assert names == [
            "trad_MeanReversion",
            "trad_SqueezeExpansion",
            "trad_TrendFollowing",
            "trad_MTFAlignment",
            "trad_LiquiditySweepReclaim",
        ]
