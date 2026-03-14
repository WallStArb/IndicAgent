from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class StochRSIPlugin:
    """Stochastic RSI — applies Stochastic normalization to RSI values.

    K = (RSI - min(RSI_window)) / (max(RSI_window) - min(RSI_window)) * 100
    D = SMA(K, d_period)

    Catches extreme overbought/oversold that plain RSI misses — RSI can sit
    at 60 for hours while StochRSI signals the local extreme.
    K < 20 = oversold extreme; K > 80 = overbought extreme.
    """

    name: str = "ind_StochRSI"
    outputs: frozenset[str] = frozenset({"stoch_rsi_k_14", "stoch_rsi_d_14"})
    min_lookback: int = 35
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 14
    d_period: int = 3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period * 2 + self.d_period:
            return {}

        close = df["close"].to_numpy(dtype=float)
        rsi_series = self._rsi_series(close, self.period)

        if len(rsi_series) < self.period + self.d_period - 1:
            return {}

        # Apply Stochastic to RSI series
        k_values = []
        for i in range(self.period - 1, len(rsi_series)):
            window = rsi_series[i - self.period + 1 : i + 1]
            lo, hi = float(np.min(window)), float(np.max(window))
            k_values.append((rsi_series[i] - lo) / (hi - lo) * 100.0 if hi > lo else 50.0)

        if len(k_values) < self.d_period:
            return {}

        k = k_values[-1]
        d = float(np.mean(k_values[-self.d_period :]))

        # Seed incremental state
        deltas = np.diff(close)
        avg_g = float(deltas[: self.period].clip(min=0).sum() / self.period)
        avg_l = float(-deltas[: self.period].clip(max=0).sum() / self.period)
        for delta in deltas[self.period :]:
            avg_g = (avg_g * (self.period - 1) + max(delta, 0.0)) / self.period
            avg_l = (avg_l * (self.period - 1) + max(-delta, 0.0)) / self.period

        self._state = {
            "avg_gain": avg_g,
            "avg_loss": avg_l,
            "prev_close": float(close[-1]),
            "rsi_window": deque(rsi_series[-self.period :].tolist(), maxlen=self.period),
            "k_window": deque(k_values[-self.d_period :], maxlen=self.d_period),
        }
        return {"stoch_rsi_k_14": round(k, 4), "stoch_rsi_d_14": round(d, 4)}

    def _rsi_series(self, close: np.ndarray, period: int) -> np.ndarray:
        """Return RSI values starting after the seed period."""
        deltas = np.diff(close)
        if len(deltas) < period:
            return np.array([])
        avg_g = float(deltas[:period].clip(min=0).sum() / period)
        avg_l = float(-deltas[:period].clip(max=0).sum() / period)
        values = []
        for delta in deltas[period:]:
            avg_g = (avg_g * (period - 1) + max(float(delta), 0.0)) / period
            avg_l = (avg_l * (period - 1) + max(-float(delta), 0.0)) / period
            values.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))
        return np.array(values)

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        curr = float(df["close"].iloc[-1])
        s = self._state

        delta = curr - s["prev_close"]
        s["avg_gain"] = (s["avg_gain"] * (self.period - 1) + max(delta, 0.0)) / self.period
        s["avg_loss"] = (s["avg_loss"] * (self.period - 1) + max(-delta, 0.0)) / self.period
        s["prev_close"] = curr

        rsi = 100.0 if s["avg_loss"] == 0 else 100.0 - 100.0 / (1.0 + s["avg_gain"] / s["avg_loss"])
        s["rsi_window"].append(rsi)

        if len(s["rsi_window"]) < self.period:
            return {}

        lo, hi = min(s["rsi_window"]), max(s["rsi_window"])
        k = (rsi - lo) / (hi - lo) * 100.0 if hi > lo else 50.0
        s["k_window"].append(k)

        if len(s["k_window"]) < self.d_period:
            return {}

        d = sum(s["k_window"]) / len(s["k_window"])
        return {"stoch_rsi_k_14": round(k, 4), "stoch_rsi_d_14": round(d, 4)}


plugin = StochRSIPlugin()
