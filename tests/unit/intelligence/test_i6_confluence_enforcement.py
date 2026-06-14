"""Sweep asserting every TIER_I7 plugin declares requires_i6_confluence.

VAL-05: All I7 plugins must declare requires_i6_confluence so the pipeline
startup gate (validate_tier) can enforce the architectural invariant.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins import registry
from src.intelligence.plugins.base import ArchitectureViolation
from src.intelligence.register_plugins import (
    _I7_I6_EXEMPT,
    TIER_I7,
    register_all_plugins,
)


class TestI6ConfluenceEnforcement:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    @pytest.mark.parametrize("plugin_name", TIER_I7)
    def test_requires_i6_confluence_declared(self, plugin_name: str):
        """Every TIER_I7 plugin must declare requires_i6_confluence as a bool attribute."""
        plugin = registry.patterns.get(plugin_name)
        assert plugin is not None, f"I7 plugin {plugin_name!r} not found in registry"
        assert hasattr(plugin, "requires_i6_confluence"), (
            f"I7 plugin {plugin_name!r} missing requires_i6_confluence declaration. "
            f"Add: requires_i6_confluence: bool = True  "
            f"(or False with TODO comment if I6 not yet integrated)"
        )
        assert isinstance(plugin.requires_i6_confluence, bool), (
            f"I7 plugin {plugin_name!r}.requires_i6_confluence must be bool, "
            f"got {type(plugin.requires_i6_confluence).__name__!r}"
        )

    def test_validate_tier_raises_no_architecture_violation(self):
        """validate_tier(TIER_I7) must not raise ArchitectureViolation when all plugins comply."""
        try:
            registry.validate_tier(TIER_I7, "I7")
        except ArchitectureViolation as error:
            pytest.fail(f"validate_tier raised ArchitectureViolation unexpectedly: {error}")

    @pytest.mark.parametrize(
        "plugin_name",
        [n for n in TIER_I7 if n not in _I7_I6_EXEMPT],
    )
    def test_requires_i6_confluence_true(self, plugin_name: str):
        """Every TIER_I7 plugin NOT in _I7_I6_EXEMPT must have requires_i6_confluence=True.

        Phase 119 mandates all in-scope I7 setups consume I6 cross-timeframe data.
        Plugins in _I7_I6_EXEMPT are temporarily exempt - refactor them in a follow-up phase.
        """
        plugin = registry.patterns.get(plugin_name)
        assert plugin is not None, f"I7 plugin {plugin_name!r} not found in registry"
        assert getattr(plugin, "requires_i6_confluence", False) is True, (
            f"Phase 119 invariant violated: I7 plugin {plugin_name!r} must have "
            f"requires_i6_confluence=True. Either add the attribute or add the plugin "
            f"to _I7_I6_EXEMPT with a follow-up phase TODO."
        )

    def test_validate_tier_rejects_false(self):
        """validate_tier() must raise ArchitectureViolation when a non-exempt I7 plugin
        has requires_i6_confluence=False — proves False (not just missing) is rejected.
        """
        # Pick a known non-exempt plugin and override its attribute
        non_exempt_name = next(n for n in TIER_I7 if n not in _I7_I6_EXEMPT)
        plugin = registry.patterns.get(non_exempt_name)
        assert plugin is not None, f"Test setup: {non_exempt_name!r} not in registry"

        original_value = plugin.requires_i6_confluence
        try:
            plugin.requires_i6_confluence = False  # type: ignore[misc]
            with pytest.raises(
                ArchitectureViolation, match="must have requires_i6_confluence=True"
            ):
                registry.validate_tier(TIER_I7, "I7")
        finally:
            plugin.requires_i6_confluence = original_value  # type: ignore[misc]

    def test_exempt_plugins_are_known(self):
        """_I7_I6_EXEMPT must have exactly 8 members; all must be in TIER_I7 and registered.

        Pins the exemption set so it cannot silently grow or reference missing plugins.
        """
        assert len(_I7_I6_EXEMPT) == 8, (
            f"_I7_I6_EXEMPT should have exactly 8 members, got {len(_I7_I6_EXEMPT)}: "
            f"{sorted(_I7_I6_EXEMPT)}"
        )
        tier_set = set(TIER_I7)
        for name in _I7_I6_EXEMPT:
            assert name in tier_set, (
                f"_I7_I6_EXEMPT member {name!r} is not in TIER_I7 - " f"remove it or update TIER_I7"
            )
            assert (
                registry.patterns.get(name) is not None
            ), f"_I7_I6_EXEMPT member {name!r} is not registered in registry"

    # ECL-compliant I7 plugins: dual-gate refactored, shadow_only=True (Phase 119+123).
    # Previously tracked via _PHASE_119_PLUGINS frozenset (dissolved in Phase 123).
    _ECL_SHADOW_PLUGINS = [
        "trad_OFISpike",
        "trad_CVDSpike",
        "trad_OFIDivergence",
        "trad_FailedBreakout",
        "trad_CandlestickPatternSetup",
        "trad_SessionExtremesSetup",
        "trad_LiquidityHunt",
        "trad_DeltaExhaustion",
        "trad_LVNBreakout",
        "trad_VWAPReclaim",
        "trad_VWAPDeviation",
        "trad_MomentumBreakout",
        "trad_ORB15",
        "trad_ORB30",
        "trad_SecondLegContinuation",
        "trad_VCP",
        "trad_DualDivergence",
    ]

    @pytest.mark.parametrize("plugin_name", _ECL_SHADOW_PLUGINS)
    def test_shadow_only_declared(self, plugin_name: str):
        """Every ECL-compliant I7 plugin must have shadow_only=True.

        Phase 119+123: these plugins have dual HMM+ECL gates, 4-factor intrinsic
        confidence composites, requires_i6_confluence=True, and shadow_only=True.
        They run in shadow mode until earning promotion through empirical proof (p<0.05, n>=100).
        """
        plugin = registry.patterns.get(plugin_name)
        assert plugin is not None, f"ECL plugin {plugin_name!r} not found in registry"
        assert getattr(plugin, "shadow_only", False) is True, (
            f"ECL plugin {plugin_name!r} must have shadow_only=True. "
            f"Set: shadow_only: bool = True as a class attribute."
        )
