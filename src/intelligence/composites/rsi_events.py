from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import is_num, threshold_cross


@dataclass
class RSIEventsPlugin:
    name: str = "evt_RSIEvents"
    outputs: set[str] = field(
        default_factory=lambda: frozenset(
            {
                "rsi_crossed_30_up",
                "rsi_crossed_70_down",
                "rsi_crossed_50_up",
                "rsi_crossed_50_down",
                "rsi_extreme_reversal",
                "rsi_bars_in_extreme",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # Constants
    _RSI_OVERSOLD: float = 30.0
    _RSI_OVERBOUGHT: float = 70.0
    _RSI_MID: float = 50.0

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        rsi = features.get("rsi_14")
        if not is_num(rsi):
            return {}

        prev = frames.get("prev_features") or {}
        prev_rsi = prev.get("rsi_14")
        out: dict[str, Any] = {}

        # Threshold crossings (require prev)
        for key, threshold, direction in [
            ("rsi_crossed_30_up", self._RSI_OVERSOLD, "up"),
            ("rsi_crossed_70_down", self._RSI_OVERBOUGHT, "down"),
            ("rsi_crossed_50_up", self._RSI_MID, "up"),
            ("rsi_crossed_50_down", self._RSI_MID, "down"),
        ]:
            out[key] = threshold_cross(prev_rsi, rsi, threshold, direction)

        # Extreme reversal: RSI in extreme zone and moving in recovery direction
        extreme_reversal = 0
        if is_num(prev_rsi):
            if rsi < self._RSI_OVERSOLD and rsi > prev_rsi:  # oversold and rising
                extreme_reversal = 1
            elif rsi > self._RSI_OVERBOUGHT and rsi < prev_rsi:  # overbought and falling
                extreme_reversal = 1
        out["rsi_extreme_reversal"] = extreme_reversal

        # Bars in extreme zone
        in_extreme = 1 if rsi < self._RSI_OVERSOLD or rsi > self._RSI_OVERBOUGHT else 0
        if in_extreme:
            self._state["bars_in_extreme"] = self._state.get("bars_in_extreme", 0) + 1
        else:
            self._state["bars_in_extreme"] = 0
        out["rsi_bars_in_extreme"] = float(self._state["bars_in_extreme"])

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = RSIEventsPlugin()
