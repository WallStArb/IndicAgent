"""Tests for I7 plugin registration."""

import pytest

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I7, register_all_plugins
from src.intelligence.trading.aggregator import TREND_SETUPS

_VALID_REGIME_TYPES = {"trend", "mean_reversion", "any"}


class TestI7Registration:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_i7_plugins_registered(self):
        """All 35 I7 plugins should be in the registry (FVGFill removed: entry-timing defect)."""
        expected_i7 = {
            "trad_TrendFollowing",
            "trad_MeanReversion",
            "trad_LiquiditySweepReclaim",
            "trad_MTFAlignment",
            "trad_SqueezeExpansion",
            "trad_VWAPDeviation",
            "trad_MomentumBreakout",
            "trad_LiquidityHunt",
            "trad_SupplyDemandSetup",
            "trad_CHoCHReversal",
            "trad_PatternCompletion",
            "trad_DivergenceStack",
            "trad_RegimeTransition",
            "trad_GapAnalysisSetup",
            "trad_CandlestickPatternSetup",
            "trad_SessionExtremesSetup",
            "trad_FailedBreakout",
            "trad_ORB15",
            "trad_ORB30",
            "trad_PrevDayLevelTest",
            "trad_SecondLegContinuation",
            "trad_VCP",
            # Phase 34-03: VWAP + Volume Profile I7 plugins
            "trad_AnchoredVWAPReversion",
            "trad_VWAPReclaim",
            "trad_POCRejection",
            "trad_HVNRejection",
            "trad_LVNBreakout",
            # Phase 036-02: OFI + CVD microstructure I7 plugins
            "trad_OFIContinuation",
            "trad_OFIDivergence",
            "trad_OFISpike",
            "trad_CVDDivergence",
            "trad_CVDSpike",
            "trad_DeltaExhaustion",
            "trad_DualDivergence",
            # Phase 037-02: Cross-asset divergence I7 plugin
            "trad_CrossAssetDivergence",
        }
        registered = set(registry.patterns.keys())
        assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"

    def test_total_plugin_count(self):
        """Should have 28 indicators + 105 patterns = 133 total (Phase 116 adds ctx_SRConsensus to TIER_I4)."""
        total = len(registry.indicators) + len(registry.patterns)
        n_ind = len(registry.indicators)
        n_pat = len(registry.patterns)
        assert total == 134, f"Expected 134, got {total} (indicators={n_ind}, patterns={n_pat})"

    @pytest.mark.unit
    def test_all_i7_plugins_have_regime_type_attribute(self):
        """Every I7 plugin must have a regime_type attribute with a valid value.

        RED: Fails until Plan 02 adds regime_type to all I7 plugin classes.
        """
        missing = []
        invalid = []
        for name in TIER_I7:
            plugin = registry.patterns.get(name)
            assert plugin is not None, f"I7 plugin {name!r} not found in registry"
            if not hasattr(plugin, "regime_type"):
                missing.append(name)
            elif plugin.regime_type not in _VALID_REGIME_TYPES:
                invalid.append(f"{name}: {plugin.regime_type!r}")

        assert not missing, f"I7 plugins missing regime_type attribute: {missing}"
        assert not invalid, (
            f"I7 plugins with invalid regime_type value (must be one of "
            f"{_VALID_REGIME_TYPES}): {invalid}"
        )

    def test_lvn_breakout_in_trend_setups(self):
        """trad_LVNBreakout must appear in TREND_SETUPS (regime_type='trend')."""
        assert "trad_LVNBreakout" in TREND_SETUPS

    def test_mean_reversion_vwap_plugins_not_in_trend_setups(self):
        """Mean-reversion and any-regime VWAP/VP plugins must NOT appear in TREND_SETUPS."""
        should_not_be_trend = {
            "trad_AnchoredVWAPReversion",
            "trad_VWAPReclaim",
            "trad_POCRejection",
            "trad_HVNRejection",
        }
        for name in should_not_be_trend:
            assert name not in TREND_SETUPS, f"{name} should NOT be in TREND_SETUPS"

    def test_tier_i7_count(self):
        """TIER_I7 should contain exactly 35 plugins (FVGFill removed: entry-timing defect)."""
        assert len(TIER_I7) == 35, f"Expected 35 TIER_I7 plugins, got {len(TIER_I7)}"
