from __future__ import annotations

from dataclasses import dataclass
from re import Pattern as RePattern
from typing import Any, ClassVar, Protocol

from src.core.models import AssetClass


class ArchitectureViolation(Exception):
    """Raised when a plugin violates a mandatory architectural constraint.

    Raised at startup in validate_tier() when a registered plugin is missing
    a required class attribute or has an invalid value. Never raised per-bar --
    architecture validation is startup-time only, not on the hot path.
    """


@dataclass
class InputSpec:
    symbol: str | RePattern[str]
    timeframe: str | list[str] = ".*"
    lookback: int = 100
    required: bool = True


class IndicatorPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]

    def compute_full(
        self, frames: dict[str, Any], *, state: dict | None = None
    ) -> dict[str, Any]: ...

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        """Incremental single-bar update using accumulated state.

        If supports_incremental=True, this method MUST document its state keys
        in a ``State keys:`` section listing every key it reads/writes, with type.
        Falls back to compute_full when state is None or empty.
        """
        ...


class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
    regime_type: ClassVar[str]  # Must be "trend", "mean_reversion", or "any"
    # PERF-03 migration flag: True when plugin has been audited and confirmed to
    # correctly use the state= parameter in compute_next() (not cold-starting every bar).
    # PluginExecutor.__init__ raises RuntimeError if any supports_incremental=True plugin
    # has this set to False. All 34 incremental plugins must set this to True.
    _state_migration_complete: ClassVar[bool]
    # fast_path flag: True when plugin meets fast-path execution criteria:
    # supports_incremental=False AND P99 latency < 100µs (verified from 24h histogram).
    # fast_path execution branch ships in Plan 05. Here only the attribute is added.
    fast_path: ClassVar[bool]

    def compute_full(
        self, frames: dict[str, Any], *, state: dict | None = None
    ) -> dict[str, Any]: ...

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        """Incremental single-bar update using accumulated state.

        If supports_incremental=True, this method MUST document its state keys
        in a ``State keys:`` section listing every key it reads/writes, with type.
        Falls back to compute_full when state is None or empty.
        """
        ...


class PluginRegistry:
    def __init__(self) -> None:
        self.indicators: dict[str, IndicatorPlugin] = {}
        self.patterns: dict[str, PatternPlugin] = {}

    def register_indicator(self, plugin: IndicatorPlugin) -> None:
        self.indicators[plugin.name] = plugin

    def register_pattern(self, plugin: PatternPlugin) -> None:
        self.patterns[plugin.name] = plugin

    def get_indicator(self, name: str) -> IndicatorPlugin | None:
        return self.indicators.get(name)

    def get_pattern(self, name: str) -> PatternPlugin | None:
        return self.patterns.get(name)

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
                        f'"trend" | "mean_reversion" | "any"'
                    )
                regime = plugin.regime_type
                if regime not in valid_regimes:
                    raise ValueError(
                        f"I7 plugin '{name}' has invalid regime_type='{regime}'. "
                        f"Must be one of: {valid_regimes}"
                    )


registry = PluginRegistry()
