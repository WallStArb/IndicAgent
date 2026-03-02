"""Tests for I7 plugin registration."""

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins


class TestI7Registration:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_i7_plugins_registered(self):
        """All 14 I7 plugins should be in the registry."""
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
            "trad_FVGFill",
            "trad_PatternCompletion",
            "trad_DivergenceStack",
            "trad_RegimeTransition",
        }
        registered = set(registry.patterns.keys())
        assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"

    def test_total_plugin_count(self):
        """Should have 23 indicators + 62 patterns = 85 total."""
        total = len(registry.indicators) + len(registry.patterns)
        n_ind = len(registry.indicators)
        n_pat = len(registry.patterns)
        assert total == 85, f"Expected 85, got {total} (indicators={n_ind}, patterns={n_pat})"
