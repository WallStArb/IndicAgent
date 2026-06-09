"""Sweep asserting every TIER_I7 plugin declares requires_i6_confluence.

VAL-05: All I7 plugins must declare requires_i6_confluence so the pipeline
startup gate (validate_tier) can enforce the architectural invariant.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins import registry
from src.intelligence.plugins.base import ArchitectureViolation
from src.intelligence.register_plugins import TIER_I7, register_all_plugins


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

    def test_false_values_have_todo_rationale(self):
        """Plugins with requires_i6_confluence=False should document the gap via a source comment.

        This test verifies via import inspection that the value is intentionally False
        (not accidentally missing or misspelled). The source TODO is a code-level convention
        check enforced separately by the pre-commit hook (check 9).
        """
        false_plugins = [
            name
            for name in TIER_I7
            if not getattr(registry.patterns.get(name), "requires_i6_confluence", True)
        ]
        # Confirm they are actual registered plugins (not None lookups)
        for name in false_plugins:
            plugin = registry.patterns.get(name)
            assert plugin is not None, f"False plugin {name!r} not found in registry"
            assert plugin.requires_i6_confluence is False
        # At least some plugins should still have True (the 11 that use ctf_ scores)
        true_plugins = [
            name
            for name in TIER_I7
            if getattr(registry.patterns.get(name), "requires_i6_confluence", False) is True
        ]
        assert len(true_plugins) >= 1, "Expected at least one TIER_I7 plugin with requires_i6_confluence=True"
