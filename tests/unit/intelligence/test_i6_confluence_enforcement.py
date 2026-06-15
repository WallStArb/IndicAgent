"""Sweep asserting I7 plugin architecture invariants.

Phase 126-06: per-plugin confluence enforcement removed. Annotation is now
pipeline-layer responsibility (_annotate_signal in signal_processor.py). This
file retains the shadow_only and validate_tier(no-raise) coverage.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins import registry
from src.intelligence.plugins.base import ArchitectureViolation
from src.intelligence.register_plugins import (
    TIER_I7,
    register_all_plugins,
)

register_all_plugins()
_ECL_SHADOW_PLUGINS = sorted(
    name for name in TIER_I7 if getattr(registry.patterns.get(name), "shadow_only", False)
)


class TestI7ArchitectureInvariants:
    def setup_method(self):
        registry.indicators.clear()
        registry.patterns.clear()
        register_all_plugins()

    def test_validate_tier_raises_no_architecture_violation(self):
        """validate_tier(TIER_I7) must not raise ArchitectureViolation."""
        try:
            registry.validate_tier(TIER_I7, "I7")
        except ArchitectureViolation as error:
            pytest.fail(f"validate_tier raised ArchitectureViolation unexpectedly: {error}")

    @pytest.mark.parametrize("plugin_name", _ECL_SHADOW_PLUGINS)
    def test_shadow_only_declared(self, plugin_name: str):
        """Every ECL-compliant I7 plugin with shadow_only=True must actually have it set.

        Phase 119+123: these plugins have dual HMM+ECL gates, 4-factor intrinsic
        confidence composites, and shadow_only=True. They run in shadow mode until
        earning promotion through empirical proof (p<0.05, n>=100).
        """
        plugin = registry.patterns.get(plugin_name)
        assert plugin is not None, f"ECL plugin {plugin_name!r} not found in registry"
        assert getattr(plugin, "shadow_only", False) is True, (
            f"ECL plugin {plugin_name!r} must have shadow_only=True. "
            f"Set: shadow_only: bool = True as a class attribute."
        )
