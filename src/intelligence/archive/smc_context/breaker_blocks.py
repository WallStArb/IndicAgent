"""smc_BreakerBlocks — Breaker block detection.

A breaker block forms when a valid order block (OB) is fully mitigated (price
runs through it), then price returns to the zone from the opposite side. The
mitigated OB "flips" its polarity:

  Bullish OB → mitigated → becomes bearish breaker block (resistance)
  Bearish OB → mitigated → becomes bullish breaker block (support)

This plugin reads OB fields from the features dict produced by smc_OrderBlocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr


@dataclass
class BreakerBlocksPlugin:
    """Detect active breaker blocks from mitigated order blocks."""

    name: str = "smc_BreakerBlocks"
    outputs: frozenset[str] = frozenset(
        {
            "breaker_block_active",
            "breaker_block_type",
            "breaker_block_top",
            "breaker_block_bottom",
            "breaker_dist_atr",
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
        close = float(df["close"].iloc[-1])
        atr = get_atr(features)

        ob_type = features.get("ob_type")
        ob_top = features.get("ob_top")
        ob_bottom = features.get("ob_bottom")
        ob_mitigated = features.get("ob_mitigated")

        if not all(isinstance(v, (int, float)) for v in [ob_type, ob_top, ob_bottom]):
            # Try to use stored breaker from state
            return self._from_state(close, atr)

        ob_type = float(ob_type)
        ob_top = float(ob_top)
        ob_bottom = float(ob_bottom)
        mitigated = isinstance(ob_mitigated, (int, float)) and float(ob_mitigated) == 1.0

        if mitigated and ob_top > ob_bottom:
            # OB is mitigated — store as candidate breaker (flipped polarity)
            breaker_type = -ob_type  # flip polarity
            self._state["breaker"] = {
                "type": breaker_type,
                "top": ob_top,
                "bottom": ob_bottom,
            }

        return self._from_state(close, atr)

    def _from_state(self, close: float, atr: Any) -> dict[str, Any]:
        breaker = self._state.get("breaker")
        if not breaker:
            return {
                "breaker_block_active": 0.0,
                "breaker_block_type": 0.0,
                "breaker_block_top": None,
                "breaker_block_bottom": None,
                "breaker_dist_atr": None,
            }

        top = breaker["top"]
        bottom = breaker["bottom"]
        btype = breaker["type"]

        # Active if price has returned to the zone from the opposite side
        in_zone = bottom <= close <= top
        # Bullish breaker (type=1): price approaches from below
        # Bearish breaker (type=-1): price approaches from above
        active = 0.0
        if in_zone:
            active = 1.0
        elif btype == 1 and close < bottom:
            active = 1.0  # below bullish breaker — still relevant
        elif btype == -1 and close > top:
            active = 1.0  # above bearish breaker — still relevant

        dist_atr = None
        if atr is not None:
            midpoint = (top + bottom) / 2
            dist_atr = abs(close - midpoint) / atr

        return {
            "breaker_block_active": active,
            "breaker_block_type": float(btype),
            "breaker_block_top": float(top),
            "breaker_block_bottom": float(bottom),
            "breaker_dist_atr": round(dist_atr, 4) if dist_atr is not None else None,
        }


plugin = BreakerBlocksPlugin()
