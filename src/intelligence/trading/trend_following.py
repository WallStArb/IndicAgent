"""I7 Trend Following setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class TrendFollowingPlugin:
    """Trend-following setup: fires when regime = trending with structure confirmation.

    Reads I4 trend_regime, I3 swing_pattern/trend_strength, I6 ctf_score from frames["features"].
    Entry at current price, stop ATR-based, targets at 1R/2R/3R.
    """

    name: str = "trad_TrendFollowing"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    regime_threshold: float = 0.5
    confidence_threshold: float = 0.4
    atr_stop_multiplier: float = 1.5
    atr_target_multipliers: tuple = (1.0, 2.0, 3.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        trend_regime = features.get("trend_regime", 0.0)
        trend_conf = features.get("trend_confidence", 0.0)
        swing_pattern = features.get("swing_pattern", 0.0)
        trend_strength = features.get("trend_strength", 0.0)
        ctf_score = features.get("ctf_score", 0.0)
        atr = features.get("atr_14", 0.0)

        if abs(trend_regime) < self.regime_threshold or trend_conf < self.confidence_threshold:
            return self._no_signal()

        direction = 1 if trend_regime > 0 else -1
        if direction == 1 and swing_pattern <= 0:
            return self._no_signal()
        if direction == -1 and swing_pattern >= 0:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        price = float(close[-1])
        low = df["low"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = price
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        raw_conf = (
            0.35 * min(1.0, abs(trend_regime))
            + 0.25 * min(1.0, trend_conf)
            + 0.20 * min(1.0, abs(trend_strength))
            + 0.20 * min(1.0, abs(ctf_score))
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        supporting = []
        if abs(trend_regime) >= 0.7:
            supporting.append("strong_trend_regime")
        if abs(ctf_score) >= 0.5:
            supporting.append("cross_timeframe_aligned")
        if abs(swing_pattern) >= 0.5:
            supporting.append("structure_confirmed")

        # Zone friction penalty
        in_supply = float(features.get("in_supply_zone", 0.0))
        in_demand = float(features.get("in_demand_zone", 0.0))
        supply_str = float(features.get("supply_strength", 0.0))
        demand_str = float(features.get("demand_strength", 0.0))
        if direction == 1 and in_supply == 1.0:
            confidence -= 0.12 * supply_str
            supporting.append("penalty_supply_zone_friction")
        elif direction == -1 and in_demand == 1.0:
            confidence -= 0.12 * demand_str
            supporting.append("penalty_demand_zone_friction")
        confidence = round(min(0.95, max(0.10, confidence)), 4)

        signal_type = "trend_long" if direction == 1 else "trend_short"
        regime_ctx = "bullish" if direction == 1 else "bearish"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = TrendFollowingPlugin()
