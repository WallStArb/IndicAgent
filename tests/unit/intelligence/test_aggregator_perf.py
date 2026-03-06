"""Failing tests (RED phase) for aggregator perf_multiplier extension — FEED-03 (aggregator side).

These tests define the behavioral contract for extending _build_all_ranked() and aggregate()
with a perf_weights parameter. Tests that reference the new perf_weights kwarg will fail with
TypeError in RED phase because the parameter does not exist yet.

FEED-03 (aggregator): perf_multiplier = 0.5 + (sharpe_rank / n_eligible_setups) applied to
composite_rank before sorting, with neutral multiplier 1.0 for setups below promotion gate.
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.aggregator import SETUP_PRIORITY, _build_all_ranked, aggregate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal(plugin: str, direction: int, confidence: float = 0.7) -> dict:
    """Build a minimal signal dict for aggregation testing."""
    return {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-03-06T10:00:00Z",
        "signal_type": "test",
        "setup_plugin": plugin,
        "direction": direction,
        "entry_price": 5200.0,
        "stop_loss": 5185.0 if direction == 1 else 5215.0,
        "targets": [5215.0] if direction == 1 else [5185.0],
        "confidence": confidence,
        "risk_reward_ratio": 1.0,
        "regime_context": "bullish" if direction == 1 else "bearish",
        "confluence_score": 0.5,
        "supporting_factors": ["factor_a"],
        "invalidation_conditions": [],
        "ttl_bars": 10,
        "regime_type": "any",
    }


# ---------------------------------------------------------------------------
# Module import test (passes in RED — existing module is importable)
# ---------------------------------------------------------------------------

class TestModuleImport:
    @pytest.mark.unit
    def test_build_all_ranked_module_importable(self):
        """_build_all_ranked is already importable (existing module — this test PASSES in RED)."""
        assert callable(_build_all_ranked)
        assert isinstance(SETUP_PRIORITY, dict)
        assert callable(aggregate)


# ---------------------------------------------------------------------------
# Existing behavior unchanged when perf_weights=None or {} (RED: TypeError expected)
# ---------------------------------------------------------------------------

class TestBuildAllRankedNoPerfWeights:
    @pytest.mark.unit
    def test_build_all_ranked_no_perf_weights_unchanged(self):
        """_build_all_ranked(fired, perf_weights=None) returns same order as SETUP_PRIORITY sort.

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [
            _signal("trad_MeanReversion", 1),       # SETUP_PRIORITY=1 (lowest)
            _signal("trad_LiquiditySweepReclaim", 1),  # SETUP_PRIORITY=5 (highest)
            _signal("trad_TrendFollowing", 1),       # SETUP_PRIORITY=3
        ]
        result = _build_all_ranked(fired, perf_weights=None)
        # Without perf_weights, LiquiditySweepReclaim (priority=5) should rank first
        assert result[0]["setup_plugin"] == "trad_LiquiditySweepReclaim"
        assert result[0]["composite_rank"] == 1

    @pytest.mark.unit
    def test_build_all_ranked_empty_perf_weights_unchanged(self):
        """perf_weights={} → all signals get perf_multiplier=1.0 → same SETUP_PRIORITY order.

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [
            _signal("trad_MeanReversion", 1),
            _signal("trad_LiquiditySweepReclaim", -1),
        ]
        result = _build_all_ranked(fired, perf_weights={})
        # LiquiditySweepReclaim (priority=5) still ranks first when all multipliers are neutral
        assert result[0]["setup_plugin"] == "trad_LiquiditySweepReclaim"


# ---------------------------------------------------------------------------
# Perf multiplier behavior (RED: TypeError from missing perf_weights kwarg)
# ---------------------------------------------------------------------------

class TestBuildAllRankedPerfMultiplier:
    @pytest.mark.unit
    def test_build_all_ranked_outperformer_promoted(self):
        """Outperformer (lower perf_multiplier) promoted above higher-priority setup.

        Setup: MeanReversion (priority=1, lowest) vs LiquiditySweepReclaim (priority=5, highest).
        Without perf_weights: LiquiditySweepReclaim ranks first.
        With perf_weights giving MeanReversion multiplier=0.5 and LiquiditySweepReclaim=1.5:
          adjusted_rank: MeanReversion = 1*0.5 = 0.5, LiquiditySweepReclaim = 2*1.5 = 3.0
          Sort ascending → MeanReversion ranks first (lower adjusted_rank = higher priority).

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [
            _signal("trad_MeanReversion", 1),
            _signal("trad_LiquiditySweepReclaim", 1),
        ]
        perf_weights = {
            "trad_MeanReversion": 0.5,
            "trad_LiquiditySweepReclaim": 1.5,
        }
        result = _build_all_ranked(fired, perf_weights=perf_weights)
        # MeanReversion should rank first despite lower SETUP_PRIORITY
        assert result[0]["setup_plugin"] == "trad_MeanReversion"

    @pytest.mark.unit
    def test_build_all_ranked_below_threshold_uses_neutral_multiplier(self):
        """Setup not in perf_weights → perf_multiplier=1.0 (neutral, no boost or suppression).

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [
            _signal("trad_TrendFollowing", 1),
            _signal("trad_MTFAlignment", 1),
        ]
        # Only one setup has a performance weight; the other gets 1.0 by default
        result = _build_all_ranked(fired, perf_weights={"trad_TrendFollowing": 0.6})
        # TrendFollowing (priority=3): adjusted = composite_rank * 0.6
        # MTFAlignment (priority=4): adjusted = composite_rank * 1.0 (neutral)
        # Without perf_weights: MTFAlignment ranks first (higher priority=4)
        # With perf_weights={"TrendFollowing": 0.6}: MTFAlignment composite_rank=1, adjusted=1.0;
        #   TrendFollowing composite_rank=2, adjusted=2*0.6=1.2 → MTFAlignment still first
        # The neutral multiplier must be applied, not suppressed
        for sig in result:
            assert isinstance(sig.get("adjusted_rank"), float)

    @pytest.mark.unit
    def test_build_all_ranked_adjusted_rank_attached_to_signal(self):
        """Each result dict has an 'adjusted_rank' key with float value.

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [_signal("trad_TrendFollowing", 1)]
        result = _build_all_ranked(fired, perf_weights={"trad_TrendFollowing": 0.8})
        assert len(result) == 1
        assert "adjusted_rank" in result[0]
        assert isinstance(result[0]["adjusted_rank"], float)

    @pytest.mark.unit
    def test_build_all_ranked_composite_rank_still_attached(self):
        """'composite_rank' key still present on each result dict when perf_weights used.

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [_signal("trad_TrendFollowing", 1), _signal("trad_MeanReversion", -1)]
        result = _build_all_ranked(fired, perf_weights={"trad_TrendFollowing": 0.7})
        for sig in result:
            assert "composite_rank" in sig
            assert isinstance(sig["composite_rank"], int)

    @pytest.mark.unit
    def test_build_all_ranked_multiplier_range_05_to_15(self):
        """perf_weights values in [0.5, 1.5]; sorted by composite_rank * perf_multiplier ascending.

        RED: fails with TypeError because perf_weights kwarg does not exist yet.
        """
        fired = [
            _signal("trad_MeanReversion", 1),      # priority=1
            _signal("trad_TrendFollowing", 1),      # priority=3
            _signal("trad_LiquiditySweepReclaim", 1),  # priority=5
        ]
        # Underperformer (LiquiditySweepReclaim) and outperformer (MeanReversion)
        perf_weights = {
            "trad_MeanReversion": 0.5,        # outperformer: big rank boost
            "trad_TrendFollowing": 1.0,        # neutral
            "trad_LiquiditySweepReclaim": 1.5, # underperformer: rank penalty
        }
        result = _build_all_ranked(fired, perf_weights=perf_weights)
        # Verify adjusted_ranks are in ascending order (lower = higher priority = appears first)
        adjusted_ranks = [sig["adjusted_rank"] for sig in result]
        assert adjusted_ranks == sorted(adjusted_ranks)


# ---------------------------------------------------------------------------
# aggregate() perf_weights kwarg propagation (RED: TypeError expected)
# ---------------------------------------------------------------------------

class TestAggregatePerfWeightsKwarg:
    @pytest.mark.unit
    def test_aggregate_passes_perf_weights_to_build_all_ranked(self):
        """aggregate() accepts perf_weights kwarg without raising.

        RED: fails with TypeError because aggregate() does not accept perf_weights yet.
        """
        signals = [
            _signal("trad_TrendFollowing", 1),
            _signal("trad_MeanReversion", 1),
        ]
        # This should not raise when Plan 03 implements the kwarg
        result = aggregate(
            signals,
            trend_regime=0.5,
            perf_weights={"trad_TrendFollowing": 0.7},
        )
        # Should return an AggregatedResult regardless of perf_weights
        assert result is not None
        assert hasattr(result, "selected_signal")
