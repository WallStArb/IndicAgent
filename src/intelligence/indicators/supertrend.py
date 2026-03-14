from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class SupertrendPlugin:
    """ATR-based binary trend direction indicator.

    Ratcheting band that only moves in the trend's favor.
    Flips direction on price crossover.
    """

    name: str = "Supertrend"
    outputs: frozenset[str] = frozenset({"supertrend_value", "supertrend_dir"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    period: int = 10
    multiplier: float = 3.0
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        n = len(close)

        # Compute ATR using Wilder's smoothing
        tr = np.zeros(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        alpha = 1.0 / self.period
        atr = float(np.mean(tr[1 : self.period + 1]))
        atr_series = np.zeros(n)
        atr_series[self.period] = atr
        for i in range(self.period + 1, n):
            atr = (1 - alpha) * atr + alpha * tr[i]
            atr_series[i] = atr

        # Supertrend calculation
        hl2 = (high + low) / 2.0
        direction = 1  # Start bullish
        final_upper = hl2[self.period] + self.multiplier * atr_series[self.period]
        final_lower = hl2[self.period] - self.multiplier * atr_series[self.period]

        for i in range(self.period + 1, n):
            basic_upper = hl2[i] + self.multiplier * atr_series[i]
            basic_lower = hl2[i] - self.multiplier * atr_series[i]

            # Ratchet: upper can only move DOWN, lower can only move UP
            if close[i - 1] <= final_upper:
                final_upper = min(basic_upper, final_upper)
            else:
                final_upper = basic_upper

            if close[i - 1] >= final_lower:
                final_lower = max(basic_lower, final_lower)
            else:
                final_lower = basic_lower

            # Direction flip
            if direction == 1 and close[i] < final_lower:
                direction = -1
            elif direction == -1 and close[i] > final_upper:
                direction = 1

        supertrend_value = final_lower if direction == 1 else final_upper

        self._state = {
            "prev_final_upper": float(final_upper),
            "prev_final_lower": float(final_lower),
            "prev_direction": direction,
            "prev_close": float(close[-1]),
            "prev_atr": float(atr_series[-1]),
        }

        return {
            "supertrend_value": float(supertrend_value),
            "supertrend_dir": direction,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])

        s = self._state
        alpha = 1.0 / self.period
        tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))
        atr = (1 - alpha) * s["prev_atr"] + alpha * tr

        hl2 = (h + lo) / 2.0
        basic_upper = hl2 + self.multiplier * atr
        basic_lower = hl2 - self.multiplier * atr

        if s["prev_close"] <= s["prev_final_upper"]:
            final_upper = min(basic_upper, s["prev_final_upper"])
        else:
            final_upper = basic_upper

        if s["prev_close"] >= s["prev_final_lower"]:
            final_lower = max(basic_lower, s["prev_final_lower"])
        else:
            final_lower = basic_lower

        direction = s["prev_direction"]
        if direction == 1 and c < final_lower:
            direction = -1
        elif direction == -1 and c > final_upper:
            direction = 1

        supertrend_value = final_lower if direction == 1 else final_upper

        self._state = {
            "prev_final_upper": final_upper,
            "prev_final_lower": final_lower,
            "prev_direction": direction,
            "prev_close": c,
            "prev_atr": atr,
        }

        return {
            "supertrend_value": float(supertrend_value),
            "supertrend_dir": direction,
        }


plugin = SupertrendPlugin()
