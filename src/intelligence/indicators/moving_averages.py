from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class MovingAveragesPlugin:
    name: str = "MovingAverages"
    outputs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "sma_20",
                "sma_50",
                "sma_100",
                "sma_200",
                "ema_8",
                "ema_9",
                "ema_13",
                "ema_21",
                "ema_55",
            }
        )
    )
    min_lookback: int = 60
    supports_incremental: bool = True
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"trend"}))
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)

    sma_periods: list[int] = field(default_factory=lambda: [20, 50, 100, 200])
    ema_periods: list[int] = field(default_factory=lambda: [8, 9, 13, 21, 55])
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < min(self.sma_periods + self.ema_periods) + 1:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}

        for p in self.sma_periods:
            try:
                sma_series = close.rolling(window=p, min_periods=p).mean()
                val = sma_series.iloc[-1]
                if pd.notna(val):
                    out[f"sma_{p}"] = float(val)
            except Exception:
                pass

        for p in self.ema_periods:
            try:
                ema_series = close.ewm(span=p, adjust=False, min_periods=p).mean()
                val = ema_series.iloc[-1]
                if pd.notna(val):
                    out[f"ema_{p}"] = float(val)
            except Exception:
                pass

        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract rolling window and EMA state for incremental updates."""
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]

        # SMA: keep rolling window + running sum
        for p in self.sma_periods:
            if len(close) < p:
                continue
            window_data = close.iloc[-p:].tolist()
            self._state[f"sma_{p}"] = {
                "window": deque(window_data, maxlen=p),
                "sum": sum(window_data),
            }

        # EMA: keep last value
        for p in self.ema_periods:
            if len(close) < p:
                continue
            ema_val = close.ewm(span=p, adjust=False, min_periods=p).mean().iloc[-1]
            if pd.notna(ema_val):
                self._state[f"ema_{p}"] = float(ema_val)

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}

        # SMA incremental: sliding window with running sum
        for p in self.sma_periods:
            key = f"sma_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
            window = s["window"]
            # Subtract value that will be removed (leftmost when full)
            if len(window) == p:
                s["sum"] -= window[0]
            window.append(new_close)
            s["sum"] += new_close
            if len(window) == p:
                out[key] = s["sum"] / p

        # EMA incremental: alpha * new + (1-alpha) * prev
        for p in self.ema_periods:
            key = f"ema_{p}"
            if key not in self._state:
                continue
            alpha = 2.0 / (p + 1)
            new_ema = alpha * new_close + (1 - alpha) * self._state[key]
            self._state[key] = new_ema
            out[key] = new_ema

        return out


plugin = MovingAveragesPlugin()
