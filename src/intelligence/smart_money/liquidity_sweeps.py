from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec
from ._swing_utils import find_swing_highs, find_swing_lows


@dataclass
class LiquiditySweepsPlugin:
    """Liquidity Sweeps — stop hunts beyond swing levels.

    Bullish sweep: price wicks below a swing low but closes above it
    (smart money grabbed sell stops, then reversed).
    Bearish sweep: price wicks above a swing high but closes below it.
    """

    name: str = "smc_LiquiditySweeps"
    outputs: set[str] = frozenset(
        {
            "sweep_detected",
            "sweep_type",
            "sweep_level",
            "sweep_depth_pct",
            "sweep_reclaimed",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
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
                    if i + self.reclaim_bars < len(df):
                        if all(
                            close[i + k] > sl_price
                            for k in range(1, self.reclaim_bars + 1)
                        ):
                            reclaimed = 1.0
                    sweeps.append(
                        {
                            "type": 1.0,
                            "level": sl_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
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
                    if i + self.reclaim_bars < len(df):
                        if all(
                            close[i + k] < sh_price
                            for k in range(1, self.reclaim_bars + 1)
                        ):
                            reclaimed = 1.0
                    sweeps.append(
                        {
                            "type": -1.0,
                            "level": sh_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
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
            }

        # Return most recent sweep
        latest = max(sweeps, key=lambda s: s["bar_idx"])
        return {
            "sweep_detected": 1.0,
            "sweep_type": latest["type"],
            "sweep_level": latest["level"],
            "sweep_depth_pct": latest["depth_pct"],
            "sweep_reclaimed": latest["reclaimed"],
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquiditySweepsPlugin()
