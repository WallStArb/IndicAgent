from __future__ import annotations

from dataclasses import dataclass
from re import Pattern as RePattern
from typing import Any, ClassVar, Protocol


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

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...


class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]

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


registry = PluginRegistry()
