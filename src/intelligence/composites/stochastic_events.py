from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.common import crossover_detect, is_num, threshold_cross


@dataclass
class StochasticEventsPlugin:
    name: str = "evt_StochasticEvents"
    outputs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "stoch_cross_bullish",
                "stoch_cross_bearish",
                "stoch_oversold_reversal",
                "stoch_overbought_reversal",
                "stoch_both_oversold",
                "stoch_both_overbought",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: list[InputSpec] = field(default_factory=list)

    # Constants
    _STOCH_OVERSOLD: float = 20.0
    _STOCH_OVERBOUGHT: float = 80.0

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        k = features.get("stoch_k_14_3")
        d = features.get("stoch_d_14_3")
        if not is_num(k) or not is_num(d):
            return {}

        prev = frames.get("prev_features") or {}
        pk = prev.get("stoch_k_14_3")
        pd_val = prev.get("stoch_d_14_3")

        out: dict[str, Any] = {}
        cross_bull, cross_bear = crossover_detect(pk, k, pd_val, d)
        out["stoch_cross_bullish"] = cross_bull
        out["stoch_cross_bearish"] = cross_bear

        # K crossing 20/80 thresholds
        out["stoch_oversold_reversal"] = threshold_cross(pk, k, self._STOCH_OVERSOLD, "up")
        out["stoch_overbought_reversal"] = threshold_cross(pk, k, self._STOCH_OVERBOUGHT, "down")

        out["stoch_both_oversold"] = (
            1 if k < self._STOCH_OVERSOLD and d < self._STOCH_OVERSOLD else 0
        )
        out["stoch_both_overbought"] = (
            1 if k > self._STOCH_OVERBOUGHT and d > self._STOCH_OVERBOUGHT else 0
        )

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = StochasticEventsPlugin()
