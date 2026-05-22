"""CI adoption gate: every plugin with supports_incremental=True must use IncrementalMixin.

All plugins have been migrated (Tasks 9-14). This is now a hard assertion with no xfail
allowlist. Any plugin that sets supports_incremental=True must be an instance of
IncrementalMixin or this test fails immediately.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins.mixins import IncrementalMixin
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
)

_ALL_TIERS = [
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_SMC,
    TIER_I6,
    TIER_I7,
]


def _collect_incremental_plugins() -> list[str]:
    """Return all plugin names with supports_incremental=True across all tiers."""
    from src.intelligence.plugins import registry
    from src.intelligence.register_plugins import register_all_plugins

    register_all_plugins()

    seen: set[str] = set()
    incremental: list[str] = []
    for tier in _ALL_TIERS:
        for name in tier:
            if name in seen:
                continue
            seen.add(name)
            plugin = registry.get_indicator(name) or registry.get_pattern(name)
            if plugin is not None and getattr(plugin, "supports_incremental", False):
                incremental.append(name)
    return incremental


_INCREMENTAL_PLUGINS = _collect_incremental_plugins()


@pytest.mark.parametrize("plugin_name", _INCREMENTAL_PLUGINS)
def test_plugin_uses_incremental_mixin(plugin_name: str) -> None:
    """Every incremental plugin must be an instance of IncrementalMixin.

    Hard assertion: no xfail allowlist. All plugins have been migrated in Tasks 9-14.
    Adding supports_incremental=True to a new plugin without using IncrementalMixin
    will fail this test immediately.
    """
    from src.intelligence.plugins import registry

    plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
    assert plugin is not None, f"Plugin {plugin_name!r} not found in registry"
    assert isinstance(plugin, IncrementalMixin), (
        f"{plugin_name} has supports_incremental=True but does not use IncrementalMixin. "
        f"Migrate: class {type(plugin).__name__}(IncrementalMixin)"
    )
