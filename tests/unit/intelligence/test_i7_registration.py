"""Tests for I7 plugin registration."""

import pytest

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import TIER_I7, register_all_plugins

_VALID_REGIME_TYPES = {"trend", "mean_reversion", "any"}


class TestI7Registration:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_i7_plugins_registered(self):
        """All 17 I7 plugins should be in the registry."""
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
            "trad_GapAnalysisSetup",
            "trad_CandlestickPatternSetup",
            "trad_SessionExtremesSetup",
        }
        registered = set(registry.patterns.keys())
        assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"

    def test_total_plugin_count(self):
        """Should have 23 indicators + 67 patterns = 90 total (Tasks 5+6 add bridge composites)."""
        total = len(registry.indicators) + len(registry.patterns)
        n_ind = len(registry.indicators)
        n_pat = len(registry.patterns)
        assert total == 90, f"Expected 90, got {total} (indicators={n_ind}, patterns={n_pat})"

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

        assert not missing, (
            f"I7 plugins missing regime_type attribute: {missing}"
        )
        assert not invalid, (
            f"I7 plugins with invalid regime_type value (must be one of "
            f"{_VALID_REGIME_TYPES}): {invalid}"
        )
