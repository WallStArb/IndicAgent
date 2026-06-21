"""smc_MitigationBlocks — Order block mitigation status tracking.

Tracks how thoroughly an order block has been revisited ("mitigated") by price.
Mitigation progress is expressed as a percentage of the OB zone that price has
traded through:

  0%        → "fresh"   — OB untouched since formation
  1–99%     → "partial" — OB partially mitigated
  100%      → "void"    — OB fully consumed, no longer valid

Reads ob_top, ob_bottom, ob_mitigated from the features dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec


@dataclass
class MitigationBlocksPlugin:
    """Track order block mitigation progress."""

    name: str = "smc_MitigationBlocks"
    outputs: frozenset[str] = frozenset(
        {
            "ob_mitigation_status",
            "ob_mitigation_pct",
        }
    )
    min_lookback: int = 2
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        ob_top = features.get("ob_top")
        ob_bottom = features.get("ob_bottom")
        ob_mitigated = features.get("ob_mitigated")

        _null = {"ob_mitigation_status": None, "ob_mitigation_pct": None}

        if not all(isinstance(v, (int, float)) for v in [ob_top, ob_bottom]):
            return _null

        ob_top = float(ob_top)
        ob_bottom = float(ob_bottom)
        ob_range = ob_top - ob_bottom
        if ob_range <= 0:
            return _null

        # Fully mitigated flag from OrderBlocks plugin
        if isinstance(ob_mitigated, (int, float)) and float(ob_mitigated) == 1.0:
            return {
                "ob_mitigation_status": "void",
                "ob_mitigation_pct": 1.0,
            }

        # Track deepest penetration within OB zone via running state
        last_row = df.iloc[-1]
        low = float(last_row["low"])
        high = float(last_row["high"])

        # For bullish OB (price traded down into zone), track how far into the zone
        # For bearish OB (price traded up into zone), track similarly
        # Simplification: track max price overlap regardless of OB direction
        prev_pct = self._state.get("mitigation_pct", 0.0)

        # Overlap of [low, high] with [ob_bottom, ob_top]
        overlap_low = max(low, ob_bottom)
        overlap_high = min(high, ob_top)
        overlap = max(0.0, overlap_high - overlap_low)
        bar_pct = overlap / ob_range

        new_pct = max(prev_pct, bar_pct)
        self._state["mitigation_pct"] = new_pct

        if new_pct == 0.0:
            status = "fresh"
        elif new_pct >= 1.0:
            status = "void"
        else:
            status = "partial"

        return {
            "ob_mitigation_status": status,
            "ob_mitigation_pct": round(new_pct, 4),
        }


plugin = MitigationBlocksPlugin()
