"""Tests for I7 plugin registration."""

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins


class TestI7Registration:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_i7_plugins_registered(self):
        """All 7 I7 plugins should be in the registry."""
        expected_i7 = {
            "trad_TrendFollowing",
            "trad_MeanReversion",
            "trad_LiquiditySweepReclaim",
            "trad_MTFAlignment",
            "trad_SqueezeExpansion",
            "trad_VWAPDeviation",
            "trad_MomentumBreakout",
        }
        registered = set(registry.patterns.keys())
        assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"

    def test_total_plugin_count(self):
        """Should have 23 indicators + 34 patterns = 57 total."""
        total = len(registry.indicators) + len(registry.patterns)
        n_ind = len(registry.indicators)
        n_pat = len(registry.patterns)
        assert total == 57, f"Expected 57, got {total} (indicators={n_ind}, patterns={n_pat})"
