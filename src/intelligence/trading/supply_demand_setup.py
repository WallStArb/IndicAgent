"""trad_SupplyDemandSetup — Trade institutional supply/demand zone retests.

Fires when price enters a fresh/tested S/D zone and shows rejection.
Highest confidence when the full ICT Act 1-2-3 model is confirmed:
  sweep (Act 1) → FVG displacement (Act 2) → zone retest (Act 3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class SupplyDemandSetupPlugin:
    """I7 signal: price enters institutional S/D zone + rejection confirmation."""

    name: str = "trad_SupplyDemandSetup"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "zones", "smc"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)

    MIN_FRESHNESS: float = 0.40

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        in_demand = float(features.get("in_demand_zone", 0.0))
        in_supply = float(features.get("in_supply_zone", 0.0))

        # Gate 1: must be inside a zone
        if in_demand != 1.0 and in_supply != 1.0:
            return self._no_signal()

        # Gate 2: not both (ambiguous)
        if in_demand == 1.0 and in_supply == 1.0:
            return self._no_signal()

        if in_demand == 1.0:
            direction = 1
            freshness = float(features.get("demand_freshness", 0.0))
            strength  = float(features.get("demand_strength", 0.0))
            zone_high = float(features.get("nearest_demand_high", 0.0))
            zone_low  = float(features.get("nearest_demand_low", 0.0))
        else:
            direction = -1
            freshness = float(features.get("supply_freshness", 0.0))
            strength  = float(features.get("supply_strength", 0.0))
            zone_high = float(features.get("nearest_supply_high", 0.0))
            zone_low  = float(features.get("nearest_supply_low", 0.0))

        # Gate 3: freshness threshold
        if freshness < self.MIN_FRESHNESS:
            return self._no_signal()

        atr = float(features.get("atr_14", 0.0))
        close_arr = df["close"].to_numpy(dtype=float)
        if atr <= 0:
            high_arr = df["high"].to_numpy(dtype=float)
            low_arr  = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high_arr[-14:] - low_arr[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = float(close_arr[-1])
        supporting: list[str] = [f"{'demand' if direction == 1 else 'supply'}_zone_entry"]

        # Stop: beyond distal zone edge with buffer
        stop = (zone_low - atr * 0.25) if direction == 1 else (zone_high + atr * 0.25)

        # T1: proximal zone edge
        t1 = zone_high if direction == 1 else zone_low
        # T2: 2.5R from entry
        risk = abs(entry - stop)
        t2 = entry + risk * 2.5 if direction == 1 else entry - risk * 2.5

        # Confidence scoring
        if freshness >= 0.9:
            confidence = 0.58
        elif freshness >= 0.5:
            confidence = 0.46
        else:
            confidence = 0.35

        # Zone strength adjustment
        confidence += (strength - 0.5) * 0.20

        # Premium/discount alignment
        pip = float(features.get("price_in_premium", -1))
        if direction == 1 and pip == 0.0:
            confidence += 0.08
            supporting.append("discount_zone_aligned")
        elif direction == -1 and pip == 1.0:
            confidence += 0.08
            supporting.append("premium_zone_aligned")
        elif direction == 1 and pip == 1.0:
            confidence -= 0.06
        elif direction == -1 and pip == 0.0:
            confidence -= 0.06

        # *** ACT 1-2-3 MODEL ***
        sweep_det    = float(features.get("sweep_detected", 0.0))
        sweep_recl   = float(features.get("sweep_reclaimed", 0.0))
        sweep_type   = float(features.get("sweep_type", 0.0))
        fvg_type     = float(features.get("fvg_type", 0.0))

        act1 = sweep_det == 1.0 and sweep_recl == 1.0
        act1_dir = (
            (direction == 1 and sweep_type == 1.0)
            or (direction == -1 and sweep_type == -1.0)
        )
        act2 = fvg_type == float(direction)

        if act1 and act1_dir:
            if act2:
                confidence += 0.14
                supporting.append("act_1_2_3_confirmed")
            else:
                confidence += 0.07
                supporting.append("act_1_confirmed")

        if act2 and not act1:
            confidence += 0.09
            supporting.append("fvg_displacement")

        # Order block fully contained within zone
        ob_type   = float(features.get("ob_type", 0.0))
        ob_top    = float(features.get("ob_top", 0.0))
        ob_bottom = float(features.get("ob_bottom", 0.0))
        if (ob_type == float(direction) and
                ob_top > 0 and ob_bottom >= zone_low and ob_top <= zone_high):
            confidence += 0.08
            supporting.append("ob_zone_overlap")

        choch = float(features.get("choch_detected", 0.0))
        bos   = float(features.get("bos_detected", 0.0))
        bos_dir = float(features.get("bos_direction", 0.0))
        if choch == 1.0:
            confidence += 0.09
            supporting.append("choch_confirmed")
        elif bos == 1.0 and bos_dir == float(direction):
            confidence += 0.05
            supporting.append("bos_confirmed")

        ctf = float(features.get("ctf_score", 0.0))
        if abs(ctf) > 0.3 and math.copysign(1, ctf) == direction:
            confidence += 0.05
            supporting.append("ctf_aligned")

        confidence = round(min(0.95, max(0.10, confidence)), 4)

        sig_type = "supply_demand_long" if direction == 1 else "supply_demand_short"
        return {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": [round(t1, 2), round(t2, 2)],
            "confidence": confidence,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = SupplyDemandSetupPlugin()
