from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class StochasticEventsPlugin:
    name: str = "evt_StochasticEvents"
    outputs: set[str] = field(
        default_factory=lambda: frozenset({
            "stoch_cross_bullish", "stoch_cross_bearish",
            "stoch_oversold_reversal", "stoch_overbought_reversal",
            "stoch_both_oversold", "stoch_both_overbought",
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: list[InputSpec] = field(default_factory=list)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        k = features.get("stoch_k_14_3")
        d = features.get("stoch_d_14_3")
        if not (isinstance(k, (int, float)) and isinstance(d, (int, float))):
            return {}

        prev = frames.get("prev_features") or {}
        pk = prev.get("stoch_k_14_3")
        pd_val = prev.get("stoch_d_14_3")

        out: dict[str, Any] = {}
        cross_bull = 0
        cross_bear = 0
        if isinstance(pk, (int, float)) and isinstance(pd_val, (int, float)):
            cross_bull = 1 if pk <= pd_val and k > d else 0
            cross_bear = 1 if pk >= pd_val and k < d else 0
        out["stoch_cross_bullish"] = cross_bull
        out["stoch_cross_bearish"] = cross_bear

        # K crossing 20/80 thresholds
        out["stoch_oversold_reversal"] = 1 if isinstance(pk, (int, float)) and pk < 20 <= k else 0
        out["stoch_overbought_reversal"] = 1 if isinstance(pk, (int, float)) and pk > 80 >= k else 0

        out["stoch_both_oversold"] = 1 if k < 20 and d < 20 else 0
        out["stoch_both_overbought"] = 1 if k > 80 and d > 80 else 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = StochasticEventsPlugin()
