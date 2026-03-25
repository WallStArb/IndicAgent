from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec

# 390 1m bars/day × 252 trading days/year
_ANNUALIZATION = math.sqrt(390 * 252)


@dataclass
class HistoricalVolatilityPlugin:
    """Realized (historical) volatility: annualized std of log returns.

    hv_20      = std(log_returns, 20 bars) * sqrt(390 * 252)
    hv_ratio_20 = hv_20 / rolling_mean(hv_20, 20 bars)
                  > 1.0 → vol elevated vs recent baseline
                  < 1.0 → vol compressed vs recent baseline
    """

    name: str = "ind_HistoricalVolatility"
    outputs: frozenset[str] = frozenset({"hv_20", "hv_ratio_20"})
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        close = df["close"].to_numpy(dtype=float)
        log_returns = np.log(close[1:] / close[:-1])

        if len(log_returns) < self.period:
            return {}

        # Rolling HV values
        hv_values = [
            float(np.std(log_returns[i - self.period + 1 : i + 1], ddof=1) * _ANNUALIZATION)
            for i in range(self.period - 1, len(log_returns))
        ]

        hv_20 = hv_values[-1]
        recent = hv_values[-self.period :]
        hv_mean = float(np.mean(recent))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        self._state = {
            "prev_close": float(close[-1]),
            "log_return_window": deque(log_returns[-self.period :].tolist(), maxlen=self.period),
            "hv_window": deque(hv_values[-self.period :], maxlen=self.period),
        }

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        curr = float(df["close"].iloc[-1])
        s = self._state

        s["log_return_window"].append(math.log(curr / s["prev_close"]))
        s["prev_close"] = curr

        if len(s["log_return_window"]) < self.period:
            return {}

        hv_20 = float(np.std(list(s["log_return_window"]), ddof=1) * _ANNUALIZATION)
        s["hv_window"].append(hv_20)

        hv_mean = float(np.mean(list(s["hv_window"])))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}


plugin = HistoricalVolatilityPlugin()
