"""ExhaustionScore I2 composite plugin.

Synthesizes RSI extreme + curvature + MACD histogram slope into a tiered
exhaustion signal used by I7 setups as a guard/boost score.

Outputs:
    exhaustion_score: float in {0.0, 0.2, 0.6, 1.0}
    exhaustion_side:  "bull" | "bear" | "none"
    exhaustion_bars:  float — consecutive bars where any exhaustion holds
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils.common import is_num


@dataclass
class ExhaustionScorePlugin:
    name: str = "cmp_ExhaustionScore"
    outputs: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "exhaustion_score",
                "exhaustion_side",
                "exhaustion_bars",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: tuple = ()  # reads from frames["features"] only
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        rsi = features.get("rsi_14")
        curvature = features.get("rsi_curvature")
        hist_slope = features.get("macd_hist_slope")

        # Determine active side from RSI extreme — curvature/slope conditions
        # are evaluated only within the context of the active RSI side.
        rsi_bull = is_num(rsi) and rsi > 70
        rsi_bear = is_num(rsi) and rsi < 30

        if rsi_bull:
            # Bull exhaustion: count how many of the 3 bull conditions hold
            bull_count = (
                1  # rsi>70 already confirmed
                + (1 if is_num(curvature) and curvature < 0 else 0)
                + (1 if is_num(hist_slope) and hist_slope < 0 else 0)
            )
            bear_count = 0
        elif rsi_bear:
            # Bear exhaustion: count how many of the 3 bear conditions hold
            bull_count = 0
            bear_count = (
                1  # rsi<30 already confirmed
                + (1 if is_num(curvature) and curvature > 0 else 0)
                + (1 if is_num(hist_slope) and hist_slope > 0 else 0)
            )
        else:
            bull_count = 0
            bear_count = 0

        best = max(bull_count, bear_count)
        score_map = {3: 1.0, 2: 0.6, 1: 0.2, 0: 0.0}
        exhaustion_score = score_map[best]

        # Side determined by RSI extreme
        if rsi_bull:
            exhaustion_side = "bull"
        elif rsi_bear:
            exhaustion_side = "bear"
        else:
            exhaustion_side = "none"

        # Consecutive bar counter — state-tracked only
        if exhaustion_score > 0.0:
            self._state["exhaustion_bars"] = self._state.get("exhaustion_bars", 0.0) + 1.0
        else:
            self._state["exhaustion_bars"] = 0.0

        exhaustion_bars = self._state["exhaustion_bars"]

        return {
            "exhaustion_score": exhaustion_score,
            "exhaustion_side": exhaustion_side,
            "exhaustion_bars": exhaustion_bars,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ExhaustionScorePlugin()
