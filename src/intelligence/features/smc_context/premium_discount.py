"""smc_PremiumDiscount — Price position relative to equilibrium (50% of swing range).

In ICT theory, price is either at a "premium" (above 50% of the range — expensive
for buys, ideal for sells) or at a "discount" (below 50% — cheap for buys, ideal
for sells to cover).

Reads swing_high / swing_low from features (provided by smc_BOSCHoCH or I3 structure).

Note: smc_LiquidityPools already exposes `price_in_premium` (binary flag) and
`premium_position` (-1 to 1 scalar). This plugin provides:
  - `equilibrium_level`: absolute price at the 50% midpoint
  - `premium_discount_pct`: signed percentage relative to equilibrium
    (-1.0 = deepest discount, 0.0 = at equilibrium, +1.0 = deepest premium)

These complement the LiquidityPools fields with higher precision and the raw level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import clamp


@dataclass
class PremiumDiscountPlugin:
    """Compute equilibrium level and premium/discount percentage."""

    name: str = "smc_PremiumDiscount"
    outputs: frozenset[str] = frozenset(
        {
            "equilibrium_level",
            "premium_discount_pct",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=10),)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }

        swing_high = features.get("swing_high")
        swing_low = features.get("swing_low")

        _null = {"equilibrium_level": None, "premium_discount_pct": None}

        if not all(isinstance(v, (int, float)) for v in [swing_high, swing_low]):
            return _null

        swing_high = float(swing_high)
        swing_low = float(swing_low)
        half_range = (swing_high - swing_low) / 2.0

        if half_range <= 0:
            return _null

        equilibrium = swing_low + half_range

        # Close from features or df
        df = frames.get("main")
        close_feat = features.get("close")
        if isinstance(close_feat, (int, float)):
            close = float(close_feat)
        elif df is not None and len(df) > 0:
            close = float(df["close"].iloc[-1])
        else:
            return _null

        # premium_discount_pct: positive = premium, negative = discount
        pct = clamp((close - equilibrium) / half_range)

        return {
            "equilibrium_level": round(equilibrium, 4),
            "premium_discount_pct": round(pct, 4),
        }


plugin = PremiumDiscountPlugin()
