"""Sweep asserting every TIER_I7 plugin declares requires_i6_confluence = True.

VAL-05: All I7 plugins must declare requires_i6_confluence=True so the pipeline
startup gate (validate_tier) can enforce the architectural invariant uniformly.

Phase 126: _I7_I6_EXEMPT carve-out deleted. All 8 formerly-exempt plugins are now
compliant (requires_i6_confluence=True). No exemptions remain.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins import registry
from src.intelligence.plugins.base import ArchitectureViolation
from src.intelligence.register_plugins import (
    TIER_I7,
    register_all_plugins,
)

# Derive at module level so parametrize picks up new plugins automatically.
register_all_plugins()
_ECL_SHADOW_PLUGINS = sorted(
    name for name in TIER_I7 if getattr(registry.patterns.get(name), "shadow_only", False)
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
            f"Add: requires_i6_confluence: bool = True"
        )
        assert isinstance(plugin.requires_i6_confluence, bool), (
            f"I7 plugin {plugin_name!r}.requires_i6_confluence must be bool, "
            f"got {type(plugin.requires_i6_confluence).__name__!r}"
        )

    @pytest.mark.parametrize("plugin_name", TIER_I7)
    def test_requires_i6_confluence_true(self, plugin_name: str):
        """Every TIER_I7 plugin must have requires_i6_confluence=True.

        Phase 126 deleted the _I7_I6_EXEMPT carve-out. All plugins must be compliant.
        """
        plugin = registry.patterns.get(plugin_name)
        assert plugin is not None, f"I7 plugin {plugin_name!r} not found in registry"
        assert getattr(plugin, "requires_i6_confluence", False) is True, (
            f"Phase 126 invariant violated: I7 plugin {plugin_name!r} must have "
            f"requires_i6_confluence=True. The _I7_I6_EXEMPT carve-out no longer exists."
        )

    def test_validate_tier_raises_no_architecture_violation(self):
        """validate_tier(TIER_I7) must not raise ArchitectureViolation when all plugins comply."""
        try:
            registry.validate_tier(TIER_I7, "I7")
        except ArchitectureViolation as error:
            pytest.fail(f"validate_tier raised ArchitectureViolation unexpectedly: {error}")

    def test_validate_tier_rejects_false(self):
        """validate_tier() must raise ArchitectureViolation when an I7 plugin has
        requires_i6_confluence=False — proves False (not just missing) is rejected.
        """
        test_plugin_name = next(iter(TIER_I7))
        plugin = registry.patterns.get(test_plugin_name)
        assert plugin is not None, f"Test setup: {test_plugin_name!r} not in registry"

        original_value = plugin.requires_i6_confluence
        try:
            plugin.requires_i6_confluence = False  # type: ignore[misc]
            with pytest.raises(
                ArchitectureViolation, match="must have requires_i6_confluence=True"
            ):
                registry.validate_tier(TIER_I7, "I7")
        finally:
            plugin.requires_i6_confluence = original_value  # type: ignore[misc]

    @pytest.mark.parametrize("plugin_name", _ECL_SHADOW_PLUGINS)
    def test_shadow_only_declared(self, plugin_name: str):
        """Every ECL-compliant I7 plugin with shadow_only=True must actually have it set.

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
