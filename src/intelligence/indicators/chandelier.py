from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class ChandelierPlugin:
    """Chandelier Exit — ATR-based adaptive trailing stop levels.

    Long stop  = highest_high(period) - multiplier * ATR(period)
    Short stop = lowest_low(period)   + multiplier * ATR(period)

    Provides adaptive stop/target levels calibrated to recent volatility.
    Uses period=22, multiplier=3.0 by default (Wilder's recommendation).
    """

    name: str = "ind_ChandelierExit"
    outputs: set[str] = frozenset({"chandelier_long_22", "chandelier_short_22"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 22
    multiplier: float = 3.0
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        atr = self._compute_atr(high, low, close, self.period)
        highest_high = float(np.max(high[-self.period:]))
        lowest_low = float(np.min(low[-self.period:]))

        self._state = {
            "atr": atr,
            "prev_close": float(close[-1]),
            "high_window": deque(high[-self.period:].tolist(), maxlen=self.period),
            "low_window": deque(low[-self.period:].tolist(), maxlen=self.period),
        }

        return {
            "chandelier_long_22": round(highest_high - self.multiplier * atr, 6),
            "chandelier_short_22": round(lowest_low + self.multiplier * atr, 6),
        }

    def _compute_atr(
        self, high: np.ndarray, low_price: np.ndarray, close: np.ndarray, period: int
    ) -> float:
        """Wilder's ATR: SMA seed then Wilder smoothing (alpha = 1/period)."""
        n = len(high)
        tr = np.empty(n)
        tr[0] = high[0] - low_price[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low_price[i],
                abs(high[i] - close[i - 1]),
                abs(low_price[i] - close[i - 1]),
            )
        atr = float(np.mean(tr[1: period + 1]))
        alpha = 1.0 / period
        for i in range(period + 1, n):
            atr = (1 - alpha) * atr + alpha * float(tr[i])
        return atr

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        h = float(row["high"])
        low_price = float(row["low"])
        c = float(row["close"])
        s = self._state

        tr = max(h - low_price, abs(h - s["prev_close"]), abs(low_price - s["prev_close"]))
        alpha = 1.0 / self.period
        s["atr"] = (1 - alpha) * s["atr"] + alpha * tr
        s["prev_close"] = c
        s["high_window"].append(h)
        s["low_window"].append(low_price)

        highest_high = max(s["high_window"])
        lowest_low = min(s["low_window"])

        return {
            "chandelier_long_22": round(highest_high - self.multiplier * s["atr"], 6),
            "chandelier_short_22": round(lowest_low + self.multiplier * s["atr"], 6),
        }


plugin = ChandelierPlugin()
