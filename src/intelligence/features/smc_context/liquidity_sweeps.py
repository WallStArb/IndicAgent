from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.utils.gradient_utils import linear_ramp

from .swing_utils import find_swing_highs, find_swing_lows


@dataclass
class LiquiditySweepsPlugin:
    """Liquidity Sweeps — stop hunts beyond swing levels.

    Bullish sweep: price wicks below a swing low but closes above it
    (smart money grabbed sell stops, then reversed).
    Bearish sweep: price wicks above a swing high but closes below it.
    """

    name: str = "smc_LiquiditySweeps"
    outputs: frozenset[str] = frozenset(
        {
            "sweep_detected",
            "sweep_type",
            "sweep_level",
            "sweep_depth_pct",
            "sweep_reclaimed",
            "sweep_strength",
            "reclaim_velocity",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    neighbor: int = 5
    reclaim_bars: int = 3  # Bars to check for reclaim confirmation
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        swing_highs = find_swing_highs(high, self.neighbor)
        swing_lows = find_swing_lows(low, self.neighbor)

        if not swing_highs and not swing_lows:
            return {
                "sweep_detected": 0.0,
                "sweep_type": 0.0,
                "sweep_level": 0.0,
                "sweep_depth_pct": 0.0,
                "sweep_reclaimed": 0.0,
                "sweep_strength": 0.0,
                "reclaim_velocity": 0.0,
            }

        # Check recent bars for sweeps of swing levels
        sweeps: list[dict[str, Any]] = []

        # Check for bullish sweeps (wicks below swing lows)
        for sl_idx in swing_lows:
            sl_price = float(low[sl_idx])
            # Look for bars AFTER this swing low that wick below it
            for i in range(sl_idx + self.neighbor + 1, len(df)):
                if low[i] < sl_price and close[i] > sl_price:
                    depth = (sl_price - float(low[i])) / sl_price * 100
                    # Check reclaim: next bars continue up
                    reclaimed = 0.0
                    bars_to_reclaim = self.reclaim_bars  # default if not reclaimed
                    if i + self.reclaim_bars < len(df):
                        if all(close[i + k] > sl_price for k in range(1, self.reclaim_bars + 1)):
                            reclaimed = 1.0
                    else:
                        bars_to_reclaim = self.reclaim_bars
                    # Gradient companions
                    sweep_str = linear_ramp(depth, 0, 2.0)  # 0-2% depth maps to 0-1
                    reclaim_vel = (
                        linear_ramp(1.0 / max(1, bars_to_reclaim), 0, 0.5) if reclaimed else 0.0
                    )
                    sweeps.append(
                        {
                            "type": 1.0,
                            "level": sl_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
                            "sweep_strength": round(sweep_str, 4),
                            "reclaim_velocity": round(reclaim_vel, 4),
                            "bar_idx": i,
                        }
                    )

        # Check for bearish sweeps (wicks above swing highs)
        for sh_idx in swing_highs:
            sh_price = float(high[sh_idx])
            for i in range(sh_idx + self.neighbor + 1, len(df)):
                if high[i] > sh_price and close[i] < sh_price:
                    depth = (float(high[i]) - sh_price) / sh_price * 100
                    reclaimed = 0.0
                    bars_to_reclaim = self.reclaim_bars
                    if i + self.reclaim_bars < len(df):
                        if all(close[i + k] < sh_price for k in range(1, self.reclaim_bars + 1)):
                            reclaimed = 1.0
                    sweep_str = linear_ramp(depth, 0, 2.0)
                    reclaim_vel = (
                        linear_ramp(1.0 / max(1, bars_to_reclaim), 0, 0.5) if reclaimed else 0.0
                    )
                    sweeps.append(
                        {
                            "type": -1.0,
                            "level": sh_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
                            "sweep_strength": round(sweep_str, 4),
                            "reclaim_velocity": round(reclaim_vel, 4),
                            "bar_idx": i,
                        }
                    )

        if not sweeps:
            return {
                "sweep_detected": 0.0,
                "sweep_type": 0.0,
                "sweep_level": 0.0,
                "sweep_depth_pct": 0.0,
                "sweep_reclaimed": 0.0,
                "sweep_strength": 0.0,
                "reclaim_velocity": 0.0,
            }

        # Return most recent sweep
        latest = max(sweeps, key=lambda s: s["bar_idx"])
        return {
            "sweep_detected": 1.0,
            "sweep_type": latest["type"],
            "sweep_level": latest["level"],
            "sweep_depth_pct": latest["depth_pct"],
            "sweep_reclaimed": latest["reclaimed"],
            "sweep_strength": latest["sweep_strength"],
            "reclaim_velocity": latest["reclaim_velocity"],
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquiditySweepsPlugin()
