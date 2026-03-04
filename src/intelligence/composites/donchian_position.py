"""DonchianPosition — bridge composite for Donchian channel position.

Translates price position within the Donchian channel into a [-1, +1]
directional signal: +1 = price at top (bullish), -1 = at bottom (bearish).
Feeds into CIS regime bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec, PatternPlugin


@dataclass
class DonchianPositionPlugin(PatternPlugin):
    name: str = "evt_DonchianPosition"
    outputs: frozenset[str] = field(default_factory=lambda: frozenset({"donchian_position_20"}))
    min_lookback: int = 2
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"structure", "channel"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=25),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features", {})
        df = frames.get("main")

        d_high = features.get("donchian_high_20")
        d_mid = features.get("donchian_mid_20")
        d_low = features.get("donchian_low_20")

        if df is None or d_high is None or d_mid is None or d_low is None:
            return {"donchian_position_20": 0.0}

        half_range = (float(d_high) - float(d_low)) / 2.0
        if half_range == 0:
            return {"donchian_position_20": 0.0}

        close = float(df["close"].iloc[-1])
        position = (close - float(d_mid)) / half_range
        return {"donchian_position_20": max(-1.0, min(1.0, round(position, 4)))}


plugin = DonchianPositionPlugin()
