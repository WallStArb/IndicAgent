from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import crossover_detect, is_num, threshold_cross, track_bars_ago


@dataclass
class ADXEventsPlugin:
    name: str = "evt_ADXEvents"
    outputs: set[str] = field(
        default_factory=lambda: frozenset(
            {
                "adx_trend_confirmed",
                "adx_ranging_confirmed",
                "di_cross_bullish",
                "di_cross_bearish",
                "di_cross_bars_ago",
                "di_spread",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"trend"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # Constants
    _ADX_TREND_THRESHOLD: float = 25.0
    _ADX_RANGE_THRESHOLD: float = 20.0

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        adx = features.get("adx_14")
        plus_di = features.get("plus_di_14")
        minus_di = features.get("minus_di_14")
        if not all(is_num(v) for v in [adx, plus_di, minus_di]):
            return {}

        prev = frames.get("prev_features") or {}
        prev_adx = prev.get("adx_14")
        prev_plus = prev.get("plus_di_14")
        prev_minus = prev.get("minus_di_14")

        out: dict[str, Any] = {}

        # ADX threshold crossings
        out["adx_trend_confirmed"] = threshold_cross(prev_adx, adx, self._ADX_TREND_THRESHOLD, "up")
        out["adx_ranging_confirmed"] = threshold_cross(
            prev_adx, adx, self._ADX_RANGE_THRESHOLD, "down"
        )

        # DI crossovers
        di_cross_bull, di_cross_bear = crossover_detect(prev_plus, plus_di, prev_minus, minus_di)
        out["di_cross_bullish"] = di_cross_bull
        out["di_cross_bearish"] = di_cross_bear

        out["di_cross_bars_ago"] = track_bars_ago(
            self._state, "di_cross_bars_ago", di_cross_bull or di_cross_bear
        )
        out["di_spread"] = float(plus_di - minus_di)

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ADXEventsPlugin()
