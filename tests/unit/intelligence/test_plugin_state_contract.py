"""CI test: every incremental plugin must return _state in compute_next().

Iterates all TIER_I1...TIER_I7 plugins with supports_incremental=True,
calls compute_next() with seeded state, asserts "_state" in result.

This catches violations at PR time. The matching startup check in
PluginValidator._validate_incremental_state_contract() catches them at boot.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugin_validator import build_synthetic_frames
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
    register_all_plugins,
)

_ALL_TIERS = [
    ("I1", TIER_I1),
    ("I2", TIER_I2),
    ("I3", TIER_I3),
    ("I4", TIER_I4),
    ("I5", TIER_I5),
    ("SMC", TIER_SMC),
    ("I6", TIER_I6),
    ("I7", TIER_I7),
]


def _incremental_plugins() -> list[tuple[str, str, object]]:
    register_all_plugins()
    result: list[tuple[str, str, object]] = []
    for tier_name, tier_list in _ALL_TIERS:
        for plugin_name in tier_list:
            plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
            if plugin is not None and getattr(plugin, "supports_incremental", False):
                result.append((tier_name, plugin_name, plugin))
    return result


_INCREMENTAL = _incremental_plugins()


@pytest.mark.parametrize(
    "tier_name,plugin_name,plugin",
    _INCREMENTAL,
    ids=[f"{t}-{n}" for t, n, _ in _INCREMENTAL],
)
def test_compute_next_returns_state(tier_name: str, plugin_name: str, plugin: object) -> None:
    frames = build_synthetic_frames()

    seed_result = plugin.compute_full(frames)
    assert isinstance(seed_result, dict), f"{plugin_name}: compute_full() must return dict"

    state = seed_result.get("_state")
    if not state:
        pytest.skip(f"{plugin_name}: compute_full() returned no _state (insufficient data)")

    result = plugin.compute_next(frames, state=state)
    assert isinstance(result, dict), f"{plugin_name}: compute_next() must return dict"

    # Empty dict is a valid "no signal this bar" response and exempt from the contract
    if not result:
        return

    assert "_state" in result, (
        f"{plugin_name} ({tier_name}): compute_next() returned non-empty dict without '_state'. "
        f"Fix: return {{**outputs, '_state': state}} in compute_next(). "
        f"Keys returned: {sorted(result.keys())}"
    )
