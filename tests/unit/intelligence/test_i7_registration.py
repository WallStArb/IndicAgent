"""Tests for I7 plugin registration."""

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins


class TestI7Registration:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_i7_plugins_registered(self):
        """All 5 Phase 1 I7 plugins should be in the registry."""
        expected_i7 = {
            "trad_TrendFollowing",
            "trad_MeanReversion",
            "trad_LiquiditySweepReclaim",
            "trad_MTFAlignment",
            "trad_SqueezeExpansion",
        }
        registered = set(registry.patterns.keys())
        assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"

    def test_total_plugin_count(self):
        """Should have 17 indicators + 24 patterns = 41 total (v4.3.0)."""
        total = len(registry.indicators) + len(registry.patterns)
        assert total == 41, f"Expected 41, got {total} (indicators={len(registry.indicators)}, patterns={len(registry.patterns)})"
