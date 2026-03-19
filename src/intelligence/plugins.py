from __future__ import annotations

from dataclasses import dataclass
from re import Pattern as RePattern
from typing import Any, ClassVar, Protocol

from src.core.models import AssetClass


@dataclass
class InputSpec:
    symbol: str | RePattern[str]
    timeframe: str | list[str]
    lookback: int
    required: bool = True


class IndicatorPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...


class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
    regime_type: ClassVar[str]  # Must be "trend", "mean_reversion", or "any"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...


class PluginRegistry:
    def __init__(self) -> None:
        self.indicators: dict[str, IndicatorPlugin] = {}
        self.patterns: dict[str, PatternPlugin] = {}

    def register_indicator(self, plugin: IndicatorPlugin) -> None:
        self.indicators[plugin.name] = plugin

    def register_pattern(self, plugin: PatternPlugin) -> None:
        self.patterns[plugin.name] = plugin

    def get_indicator(self, name: str) -> IndicatorPlugin:
        return self.indicators[name]

    def get_pattern(self, name: str) -> PatternPlugin:
        return self.patterns[name]

    def list_indicators(self) -> list[str]:
        return list(self.indicators.keys())

    def list_patterns(self) -> list[str]:
        return list(self.patterns.keys())

    def validate_tier(self, names: list[str], tier: str) -> None:
        """Raise ValueError at startup if any name is not in the registry.

        Checks both indicators and patterns so callers don't need to know
        which bucket a plugin lives in.

        For I7 tier, also validates regime_type declaration and value.
        """
        all_known = set(self.indicators) | set(self.patterns)
        unknown = [n for n in names if n not in all_known]
        if unknown:
            raise ValueError(
                f"Tier {tier} references unregistered plugin(s): {unknown}. "
                f"Check register_plugins.py and the TIER_* constants."
            )

        # I7 regime_type validation
        if tier == "I7":
            valid_regimes = {"trend", "mean_reversion", "any"}
            for name in names:
                plugin = self.patterns.get(name)
                if plugin is None:
                    continue  # Already caught by unknown check above
                if not hasattr(plugin, "regime_type"):
                    raise ValueError(
                        f"I7 plugin '{name}' missing regime_type declaration. "
                        f"Add: regime_type: ClassVar[str] = "
                        f"\"trend\" | \"mean_reversion\" | \"any\""
                    )
                regime = plugin.regime_type
                if regime not in valid_regimes:
                    raise ValueError(
                        f"I7 plugin '{name}' has invalid regime_type='{regime}'. "
                        f"Must be one of: {valid_regimes}"
                    )


registry = PluginRegistry()
