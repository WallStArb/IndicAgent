"""CI adoption gate: every plugin with supports_incremental=True must use IncrementalMixin.

Strategy: xfail(strict=True) with shrinking allowlist — CI stays green throughout migrations.
Each migration commit removes the plugin name from UNMIGRATED_PLUGINS.
Test flips to hard assertion when UNMIGRATED_PLUGINS is empty (Task 16).
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

# Plugins with supports_incremental=True that have NOT yet been migrated to IncrementalMixin.
# Remove each plugin name from this set when its migration commit lands.
# When this set is empty (Task 16), the test body flips to a hard assertion.
UNMIGRATED_PLUGINS: frozenset[str] = frozenset(
    {
        # Group 1A (Task 9): RSI, MACD
        "RSI",
        "MACD",
        # Group 1B (Task 10): CCI, Aroon, Chandelier, CMF
        "CCI",
        "ind_Aroon",
        "ind_ChandelierExit",
        "ind_CMF",
        # Group 1C (Task 11): HistoricalVolatility, ROC/PPO, ParabolicSAR, StochRSI, ACOscillator
        "ind_HistoricalVolatility",
        "ROC_PPO",
        "ind_ParabolicSAR",
        "ind_StochRSI",
        "ind_ACOscillator",
        # Group simple (Task 12): Bollinger, Donchian, MovingAverages, OBV, Supertrend, VWAP,
        #                          SessionLevels, MarketProfile, BollingerSqueeze
        "BollingerBands",
        "DonchianChannels",
        "MovingAverages",
        "OBV",
        "Supertrend",
        "VWAP",
        "struct_SessionLevels",
        "struct_MarketProfile",
        "BollingerSqueeze",
        # Group 3: Model-state plugins (Task 14): BOCPD, HMM (all TFs), GARCH, Kalman
        "smc_BOCPDChangePoint",
        "smc_HMMRegime_1m",
        "smc_HMMRegime_5m",
        "smc_HMMRegime_15m",
        "smc_HMMRegime_1h",
        "ctx_GARCHVolatility",
        "ctx_KalmanTrend",
    }
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
@pytest.mark.xfail(strict=True, reason="not yet migrated to IncrementalMixin")
def test_plugin_uses_incremental_mixin(plugin_name: str) -> None:
    """Every incremental plugin must be an instance of IncrementalMixin.

    xfail(strict=True): test is EXPECTED to fail for plugins in UNMIGRATED_PLUGINS.
    When a plugin is removed from UNMIGRATED_PLUGINS, the test starts passing —
    strict=True means a surprise pass becomes a test failure, preventing accidental
    removal of a plugin from the allowlist without completing migration.

    CI invariant: this file never intentionally causes red CI.
    """
    if plugin_name not in UNMIGRATED_PLUGINS:
        # Already migrated — skip the xfail body and run the real assertion
        pytest.skip("already migrated — passes in test_plugin_uses_incremental_mixin_migrated")

    from src.intelligence.plugins import registry

    plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
    assert plugin is not None, f"Plugin {plugin_name!r} not found in registry"
    assert isinstance(plugin, IncrementalMixin), (
        f"{plugin_name} has supports_incremental=True but does not use IncrementalMixin. "
        f"Migrate: class {type(plugin).__name__}(IncrementalMixin)"
    )


@pytest.mark.parametrize(
    "plugin_name",
    [p for p in _INCREMENTAL_PLUGINS if p not in UNMIGRATED_PLUGINS],
)
def test_plugin_uses_incremental_mixin_migrated(plugin_name: str) -> None:
    """Hard assertion: migrated plugins (not in UNMIGRATED_PLUGINS) MUST use IncrementalMixin."""
    from src.intelligence.plugins import registry

    plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
    assert plugin is not None, f"Plugin {plugin_name!r} not found in registry"
    assert isinstance(plugin, IncrementalMixin), (
        f"{plugin_name} was removed from UNMIGRATED_PLUGINS but does not use IncrementalMixin. "
        f"Either complete the migration or add back to UNMIGRATED_PLUGINS."
    )
