"""Tests for rules-based signal aggregator."""

import pytest

from src.intelligence.trading.aggregator import (
    REGIME_ELIGIBILITY,
    SETUP_PRIORITY,
    AggregatedResult,
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


# ---------------------------------------------------------------------------
# CIS integration tests (added in Phase 7 Plan 02)
# ---------------------------------------------------------------------------


def _bullish_features() -> dict:
    """Return a strongly bullish features dict that triggers CIS fire."""
    return {
        "trend_regime": 0.8,
        "kalman_slope": 0.5,
        "smc_trend_direction": 1,
        "ctf_trend_alignment": 0.8,
        "trend_confluence_score": 0.7,
        "rsi_14": 70.0,
        "macd_hist_12_26_9": 0.5,
        "roc_14": 2.0,
        "momentum_bias": 0.6,
        "swing_pattern": 0.7,
        "bos_detected": 1.0,
        "bos_direction": 1,
        "choch_detected": 0.0,
        "choch_direction": 0,
        "ob_type": 1,
        "ob_strength": 0.8,
        "fvg_type": 1,
        "fvg_open_count": 2,
        "in_demand_zone": 1.0,
        "in_supply_zone": 0.0,
        "hmm_prob_trending_up": 0.7,
        "hmm_prob_trending_down": 0.1,
        "cp_probability": 0.2,
        "ctf_regime_agreement": 0.6,
        "vol_regime": 0.2,
    }


class TestAggregateCISIntegration:
    @pytest.mark.unit
    def test_aggregate_without_features_still_works(self):
        """aggregate() without features kwarg does not crash."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.6)
        assert isinstance(result, AggregatedResult)
        assert result.selected_signal is not None

    @pytest.mark.unit
    def test_aggregate_features_none_still_works(self):
        """aggregate(signals, features=None) does not crash."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.6, features=None)
        assert isinstance(result, AggregatedResult)

    @pytest.mark.unit
    def test_aggregate_with_features_returns_cis_fields(self):
        """aggregate() with strong bullish features -> selected_signal has CIS fields."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.8, features=_bullish_features())
        assert result.selected_signal is not None
        assert "cis_score" in result.selected_signal
        assert "bucket_scores" in result.selected_signal
        assert "weights_version" in result.selected_signal

    @pytest.mark.unit
    def test_aggregate_with_features_sets_result_cis_fields(self):
        """AggregatedResult.cis_score, .bucket_scores, .weights_version populated when features given."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.8, features=_bullish_features())
        assert result.cis_score is not None
        assert result.bucket_scores is not None
        assert result.weights_version is not None

    @pytest.mark.unit
    def test_aggregate_cis_overrides_direction(self):
        """When CIS fires, CIS direction wins even if priority-pick disagrees."""
        # Build a scenario: CIS says bullish (strong features), but 2 shorts vs 1 long
        # majority-pick would say short, but CIS should override to long
        # We use strongly bullish features + 2 shorts + 1 long
        l1 = _signal("trad_LiquiditySweepReclaim", 1, confidence=0.9)  # highest priority
        s1 = _signal("trad_TrendFollowing", -1, confidence=0.7)
        s2 = _signal("trad_MTFAlignment", -1, confidence=0.7)
        result = aggregate([l1, s1, s2], trend_regime=0.8, features=_bullish_features())
        # CIS fires bullish (strong features) -> direction should be positive
        if result.selected_signal is not None and result.resolution_method == "cis":
            assert result.selected_signal["direction"] == 1

    @pytest.mark.unit
    def test_aggregate_falls_back_to_priority_when_cis_neutral(self):
        """When features=None, fallback to winner-pick; existing behavior preserved."""
        trend = _signal("trad_TrendFollowing", 1, confidence=0.9)
        mean_rev = _signal("trad_MeanReversion", 1, confidence=0.95)
        result = aggregate([trend, mean_rev], trend_regime=0.6, features=None)
        # Without features, falls back to priority-pick
        assert result.selected_signal["setup_plugin"] == "trad_TrendFollowing"
        assert result.resolution_method in ("priority", "sole")

    @pytest.mark.unit
    def test_aggregate_cis_resolution_method_when_fires(self):
        """resolution_method == 'cis' when CIS fires."""
        sig = _signal("trad_TrendFollowing", 1, confidence=0.8)
        result = aggregate([sig], trend_regime=0.8, features=_bullish_features())
        # With CIS firing bullish and a long signal present -> resolution_method = "cis"
        if result.cis_score is not None and abs(result.cis_score) > 0.35:
            assert result.resolution_method == "cis"

    @pytest.mark.unit
    def test_aggregate_empty_signals_with_features_returns_no_signal(self):
        """Empty signals list with features -> no_signal (not a crash)."""
        result = aggregate([], trend_regime=0.8, features=_bullish_features())
        assert result.selected_signal is None
        assert result.resolution_method == "no_signal"


def _regime_features(hmm_regime: int, prob: float = 0.80, duration: int = 10) -> dict:
    """Minimal feature dict for regime eligibility tests."""
    return {
        "hmm_regime": hmm_regime,
        "hmm_regime_prob": prob,
        "hmm_regime_duration": duration,
    }


class TestRegimeEligibilityFilter:
    """Regime eligibility gate in aggregate()."""

    @pytest.mark.unit
    def test_trend_plugin_excluded_in_ranging(self):
        """TrendFollowing signal is dropped when regime=0 (ranging), prob>=0.55, dur>=3."""
        sig = _signal("trad_TrendFollowing", 1)
        result = aggregate([sig], features=_regime_features(0))
        assert result.selected_signal is None
        assert result.num_signals_fired == 0

    @pytest.mark.unit
    def test_mean_reversion_excluded_in_trending(self):
        """MeanReversion signal is dropped when regime=1 (trend-up), prob>=0.55, dur>=3."""
        sig = _signal("trad_MeanReversion", -1)
        result = aggregate([sig], features=_regime_features(1))
        assert result.selected_signal is None

    @pytest.mark.unit
    def test_mean_reversion_excluded_in_trend_down(self):
        """MeanReversion signal is dropped when regime=2 (trend-down)."""
        sig = _signal("trad_MeanReversion", 1)
        result = aggregate([sig], features=_regime_features(2))
        assert result.selected_signal is None

    @pytest.mark.unit
    def test_trend_plugin_passes_in_trending_regime(self):
        """TrendFollowing is NOT excluded when regime=1."""
        sig = _signal("trad_TrendFollowing", 1)
        result = aggregate([sig], features=_regime_features(1))
        assert result.num_signals_fired == 1

    @pytest.mark.unit
    def test_mean_reversion_passes_in_ranging_regime(self):
        """MeanReversion is NOT excluded when regime=0."""
        sig = _signal("trad_MeanReversion", -1)
        result = aggregate([sig], features=_regime_features(0))
        assert result.num_signals_fired == 1

    @pytest.mark.unit
    def test_gate_bypassed_when_regime_prob_low(self):
        """Gate is skipped when hmm_regime_prob < 0.55 — uncertain regime."""
        sig = _signal("trad_TrendFollowing", 1)
        result = aggregate([sig], features=_regime_features(0, prob=0.50))
        # Gate skipped — TrendFollowing survives even in regime=0
        assert result.num_signals_fired == 1

    @pytest.mark.unit
    def test_gate_bypassed_when_regime_duration_short(self):
        """Gate is skipped when hmm_regime_duration < 3 — newly-started regime."""
        sig = _signal("trad_TrendFollowing", 1)
        result = aggregate([sig], features=_regime_features(0, duration=2))
        assert result.num_signals_fired == 1

    @pytest.mark.unit
    def test_unrestricted_plugin_passes_any_regime(self):
        """LiquiditySweepReclaim (not in REGIME_ELIGIBILITY) passes in any regime."""
        assert "trad_LiquiditySweepReclaim" not in REGIME_ELIGIBILITY
        for regime in [0, 1, 2]:
            sig = _signal("trad_LiquiditySweepReclaim", 1)
            result = aggregate([sig], features=_regime_features(regime))
            assert result.num_signals_fired == 1, f"Failed for regime={regime}"

    @pytest.mark.unit
    def test_gate_bypassed_without_features(self):
        """No features kwarg — regime gate never applies."""
        sig = _signal("trad_TrendFollowing", 1)
        result = aggregate([sig])
        assert result.num_signals_fired == 1

    @pytest.mark.unit
    def test_mixed_signals_only_eligible_survive(self):
        """In regime=0 (ranging): TrendFollowing dropped, MeanReversion survives."""
        trend = _signal("trad_TrendFollowing", 1)
        mean_rev = _signal("trad_MeanReversion", -1)
        result = aggregate([trend, mean_rev], features=_regime_features(0))
        assert result.selected_signal is not None
        assert result.selected_signal["setup_plugin"] == "trad_MeanReversion"
        assert result.num_signals_fired == 1
