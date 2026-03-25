from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class BollingerPlugin:
    name: str = "BollingerBands"
    outputs: frozenset[str] = frozenset({"bb_20_2_upper", "bb_20_2_mid", "bb_20_2_lower"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    configs: list[tuple] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.configs:
            self.configs = [(20, 2.0)]
        self.outputs = frozenset(
            {
                key
                for (p, s) in self.configs
                for key in (
                    f"bb_{p}_{int(s)}_upper",
                    f"bb_{p}_{int(s)}_mid",
                    f"bb_{p}_{int(s)}_lower",
                )
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}
        for period, std_dev in self.configs:
            if len(close) < period + 1:
                continue
            mid = close.rolling(window=period, min_periods=period).mean()
            sd = close.rolling(window=period, min_periods=period).std(ddof=0)
            upper = mid + std_dev * sd
            lower = mid - std_dev * sd
            out[f"bb_{period}_{int(std_dev)}_upper"] = float(upper.iloc[-1])
            out[f"bb_{period}_{int(std_dev)}_mid"] = float(mid.iloc[-1])
            out[f"bb_{period}_{int(std_dev)}_lower"] = float(lower.iloc[-1])
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract rolling window state for incremental Bollinger Band updates."""
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]
        for period, std_dev in self.configs:
            if len(close) < period + 1:
                continue
            window_data = close.iloc[-period:].tolist()
            key = f"bb_{period}_{int(std_dev)}"
            self._state[key] = {
                "window": deque(window_data, maxlen=period),
                "sum": sum(window_data),
                "sum_sq": sum(x * x for x in window_data),
                "std_dev": std_dev,
                "period": period,
            }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for period, std_dev in self.configs:
            key = f"bb_{period}_{int(std_dev)}"
            if key not in self._state:
                continue
            s = self._state[key]
            window = s["window"]
            # Remove oldest value from running sums
            if len(window) == period:
                old_val = window[0]
                s["sum"] -= old_val
                s["sum_sq"] -= old_val * old_val
            # Add new value
            window.append(new_close)
            s["sum"] += new_close
            s["sum_sq"] += new_close * new_close

            if len(window) == period:
                mean = s["sum"] / period
                # Population variance (ddof=0)
                variance = s["sum_sq"] / period - mean * mean
                sd = variance**0.5 if variance > 0 else 0.0
                out[f"bb_{period}_{int(std_dev)}_upper"] = mean + std_dev * sd
                out[f"bb_{period}_{int(std_dev)}_mid"] = mean
                out[f"bb_{period}_{int(std_dev)}_lower"] = mean - std_dev * sd
        return out


plugin = BollingerPlugin()
