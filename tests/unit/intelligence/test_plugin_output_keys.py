"""Output key consistency CI test for all registered plugins (Task 15).

Parametrized over all 132 plugins.
- Runs 60-bar synthetic frames through compute_full
- Asserts all output keys are strings
- Asserts no key starts with '_' except _tier_key (reserved) and _state (mixin)
- Verifies all incremental plugins are instances of IncrementalMixin
"""

from __future__ import annotations

import numpy as np
import pandas as pd
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

# Reserved underscore prefixes allowed in output dicts
_ALLOWED_UNDERSCORE_KEYS = {"_state", "_tier_key"}


def _build_test_frames(n_bars: int = 60) -> dict[str, pd.DataFrame]:
    """Build minimal synthetic OHLCV frames for output key testing."""
    rng = np.random.default_rng(42)
    close = 5000.0 * np.cumprod(1 + rng.normal(0.0001, 0.005, n_bars))
    spread = rng.uniform(0.001, 0.003, n_bars)
    open_ = close * (1 + rng.normal(0, 0.001, n_bars))
    high = np.maximum(close * (1 + spread), close)
    low = np.minimum(close * (1 - spread), close)
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    volume = rng.lognormal(10, 0.5, n_bars).astype(float)

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return {"main": df}


def _collect_all_plugins() -> list[tuple[str, object]]:
    """Return all (name, plugin) pairs across all tiers."""
    from src.intelligence.plugins import registry
    from src.intelligence.register_plugins import register_all_plugins

    register_all_plugins()

    seen: set[str] = set()
    plugins: list[tuple[str, object]] = []
    for tier in _ALL_TIERS:
        for name in tier:
            if name in seen:
                continue
            seen.add(name)
            plugin = registry.get_indicator(name) or registry.get_pattern(name)
            if plugin is not None:
                plugins.append((name, plugin))
    return plugins


_ALL_PLUGINS = _collect_all_plugins()


@pytest.mark.parametrize("plugin_name,plugin", _ALL_PLUGINS, ids=[p[0] for p in _ALL_PLUGINS])
def test_plugin_output_keys_are_strings(plugin_name: str, plugin: object) -> None:
    """All output keys from compute_full must be strings."""
    frames = _build_test_frames(n_bars=60)
    result = plugin.compute_full(frames)

    if not result:
        # Plugin returned {} -- insufficient data for 60 bars; skip key assertion
        pytest.skip(f"{plugin_name} returned empty dict for 60-bar frames")

    for key in result:
        assert isinstance(
            key, str
        ), f"Plugin {plugin_name!r}: output key {key!r} is not a string (got {type(key).__name__})"


@pytest.mark.parametrize("plugin_name,plugin", _ALL_PLUGINS, ids=[p[0] for p in _ALL_PLUGINS])
def test_plugin_output_keys_no_private_prefix(plugin_name: str, plugin: object) -> None:
    """No output key should start with '_' except _state and _tier_key (reserved).

    Plugins must not leak internal implementation details through underscore keys.
    The executor strips _state before persisting features; other underscore keys
    will be silently included and may pollute the feature vector.
    """
    frames = _build_test_frames(n_bars=60)
    result = plugin.compute_full(frames)

    if not result:
        pytest.skip(f"{plugin_name} returned empty dict for 60-bar frames")

    for key in result:
        if key.startswith("_"):
            assert key in _ALLOWED_UNDERSCORE_KEYS, (
                f"Plugin {plugin_name!r}: unexpected underscore key {key!r}. "
                f"Only {_ALLOWED_UNDERSCORE_KEYS} are allowed. "
                f"Remove or rename this key."
            )


@pytest.mark.parametrize(
    "plugin_name,plugin",
    [(n, p) for n, p in _ALL_PLUGINS if getattr(p, "supports_incremental", False)],
    ids=[n for n, p in _ALL_PLUGINS if getattr(p, "supports_incremental", False)],
)
def test_incremental_plugin_uses_mixin(plugin_name: str, plugin: object) -> None:
    """Every plugin with supports_incremental=True must be an instance of IncrementalMixin.

    This is the hard assertion (no xfail). All plugins were migrated in Tasks 9-14.
    """
    assert isinstance(plugin, IncrementalMixin), (
        f"{plugin_name} has supports_incremental=True but does not use IncrementalMixin. "
        f"Migrate: class {type(plugin).__name__}(IncrementalMixin)"
    )
