from __future__ import annotations

from collections import deque
from dataclasses import dataclass
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
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    configs: list[tuple] = None

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
        state = {}
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

            # Initialize state for incremental updates
            window_data = close.iloc[-period:].to_numpy(copy=False)
            key = f"bb_{period}_{int(std_dev)}"
            state[key] = {
                "window": deque(window_data, maxlen=period),
                "sum": float(window_data.sum()),
                "sum_sq": float((window_data**2).sum()),
                "std_dev": std_dev,
                "period": period,
            }
        out["_state"] = state
        return out

    def compute_next(
        self, windows: dict[str, pd.DataFrame], *, state: dict | None = None
    ) -> dict[str, Any]:
        if not state:
            return self.compute_full(windows)

        out: dict[str, Any] = {}
        close = windows.get("main", {}).get("close")
        if close is None or len(close) == 0:
            return {}

        for period, std_dev in self.configs:
            key = f"bb_{period}_{int(std_dev)}"
            if key not in state:
                continue

            s = state[key]
            window = s["window"]
            new_val = float(close.iloc[-1])

            # Update rolling window
            old_val = window[0] if len(window) == period else 0.0
            window.append(new_val)

            # Update running statistics
            s["sum"] += new_val - old_val
            s["sum_sq"] += new_val * new_val - old_val * old_val

            # Compute Bollinger Bands
            mean = s["sum"] / period
            variance = (s["sum_sq"] / period) - (mean**2)
            std = variance**0.5
            mid = mean
            upper = mid + std_dev * std
            lower = mid - std_dev * std

            out[f"bb_{period}_{int(std_dev)}_upper"] = float(upper)
            out[f"bb_{period}_{int(std_dev)}_mid"] = float(mid)
            out[f"bb_{period}_{int(std_dev)}_lower"] = float(lower)

        out["_state"] = state
        return out
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for period, std_dev in self.configs:
            key = f"bb_{period}_{int(std_dev)}"
            if key not in state:
                continue
            s = state[key]
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
