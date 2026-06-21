from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class FairValueGapPlugin:
    """Fair Value Gap (FVG) — 3-candle imbalance detection.

    Bullish FVG: bar3.low > bar1.high (gap up, unfilled space).
    Bearish FVG: bar3.high < bar1.low (gap down, unfilled space).
    FVGs tend to be "filled" as price retraces to them.
    """

    name: str = "smc_FairValueGap"
    outputs: frozenset[str] = frozenset(
        {
            "fvg_type",
            "fvg_top",
            "fvg_bottom",
            "fvg_midpoint",
            "fvg_size_pct",
            "fvg_open_count",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        current_price = float(df["close"].iloc[-1])

        # Scan for all FVGs - iterate backwards from most recent to oldest
        open_fvgs: list[dict[str, Any]] = []
        for i in range(len(df) - 1, 1, -1):
            bar1_high = high[i - 2]
            bar1_low = low[i - 2]
            bar3_high = high[i]
            bar3_low = low[i]

            fvg_type = 0
            fvg_top = 0.0
            fvg_bottom = 0.0

            # Bullish FVG: bar3's low is above bar1's high
            if bar3_low > bar1_high:
                fvg_type = 1
                fvg_top = float(bar3_low)
                fvg_bottom = float(bar1_high)

            # Bearish FVG: bar3's high is below bar1's low
            elif bar3_high < bar1_low:
                fvg_type = -1
                fvg_top = float(bar1_low)
                fvg_bottom = float(bar3_high)

            if fvg_type != 0:
                # Check if this FVG has been filled by subsequent price action
                # Optimized: use vectorized check instead of nested loop
                filled = False
                if i + 1 < len(df):
                    if fvg_type == 1:
                        filled = np.any(low[i + 1 :] <= fvg_bottom)
                    elif fvg_type == -1:
                        filled = np.any(high[i + 1 :] >= fvg_top)

                if not filled:
                    open_fvgs.append({"type": fvg_type, "top": fvg_top, "bottom": fvg_bottom})

        if not open_fvgs:
            return {
                "fvg_type": 0.0,
                "fvg_top": 0.0,
                "fvg_bottom": 0.0,
                "fvg_midpoint": 0.0,
                "fvg_size_pct": 0.0,
                "fvg_open_count": 0.0,
            }

        # Return the most recent unfilled FVG
        latest = open_fvgs[-1]
        mid = (latest["top"] + latest["bottom"]) / 2
        size_pct = (
            (latest["top"] - latest["bottom"]) / current_price * 100 if current_price != 0 else 0.0
        )

        return {
            "fvg_type": float(latest["type"]),
            "fvg_top": latest["top"],
            "fvg_bottom": latest["bottom"],
            "fvg_midpoint": mid,
            "fvg_size_pct": size_pct,
            "fvg_open_count": float(len(open_fvgs)),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FairValueGapPlugin()
