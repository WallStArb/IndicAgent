from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class ADXEventsPlugin:
    name: str = "evt_ADXEvents"
    outputs: set[str] = field(
        default_factory=lambda: frozenset({
            "adx_trend_confirmed", "adx_ranging_confirmed",
            "di_cross_bullish", "di_cross_bearish", "di_cross_bars_ago",
            "di_spread",
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"trend"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        adx = features.get("adx_14")
        plus_di = features.get("plus_di_14")
        minus_di = features.get("minus_di_14")
        if not all(isinstance(v, (int, float)) for v in [adx, plus_di, minus_di]):
            return {}

        prev = frames.get("prev_features") or {}
        prev_adx = prev.get("adx_14")
        prev_plus = prev.get("plus_di_14")
        prev_minus = prev.get("minus_di_14")

        out: dict[str, Any] = {}

        # ADX threshold crossings
        trend_confirmed = 0
        ranging_confirmed = 0
        if isinstance(prev_adx, (int, float)):
            trend_confirmed = 1 if prev_adx < 25 <= adx else 0
            ranging_confirmed = 1 if prev_adx > 20 >= adx else 0
        out["adx_trend_confirmed"] = trend_confirmed
        out["adx_ranging_confirmed"] = ranging_confirmed

        # DI crossovers
        di_cross_bull = 0
        di_cross_bear = 0
        if isinstance(prev_plus, (int, float)) and isinstance(prev_minus, (int, float)):
            di_cross_bull = 1 if prev_plus <= prev_minus and plus_di > minus_di else 0
            di_cross_bear = 1 if prev_plus >= prev_minus and plus_di < minus_di else 0
        out["di_cross_bullish"] = di_cross_bull
        out["di_cross_bearish"] = di_cross_bear

        if di_cross_bull or di_cross_bear:
            self._state["di_cross_bars_ago"] = 0.0
        else:
            self._state["di_cross_bars_ago"] = float(
                min(self._state.get("di_cross_bars_ago", 999) + 1, 999)
            )
        out["di_cross_bars_ago"] = self._state["di_cross_bars_ago"]
        out["di_spread"] = float(plus_di - minus_di)

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ADXEventsPlugin()
