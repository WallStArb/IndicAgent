"""Bollinger Bands plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full Bollinger computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract rolling window state from full computation
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, get_main_df


@dataclass
class BollingerPlugin(IncrementalMixin):
    name: str = "BollingerBands"
    outputs: frozenset[str] = frozenset({"bb_20_2_upper", "bb_20_2_mid", "bb_20_2_lower"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    configs: list[tuple] | None = field(default=None)

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

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full Bollinger computation. Returns outputs only (no _state)."""
        df = get_main_df(frames, self.min_lookback)
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
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract rolling window state for incremental updates."""
        df = get_main_df(frames, 1)
        if df is None:
            return {}
        close = df["close"]
        state: dict = {}
        for period, std_dev in self.configs:
            if len(close) < period:
                continue
            window_data = close.iloc[-period:].to_numpy(copy=False)
            key = f"bb_{period}_{int(std_dev)}"
            state[key] = {
                "window": deque(window_data, maxlen=period),
                "sum": float(window_data.sum()),
                "sum_sq": float((window_data**2).sum()),
                "std_dev": std_dev,
                "period": period,
            }
        return state

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental Bollinger update. Mutates state in place."""
        df = get_main_df(windows, 1)
        if df is None:
            return {}
        close = df["close"]
        if len(close) == 0:
            return {}

        out: dict[str, Any] = {}
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
            std = max(variance, 0) ** 0.5
            mid = mean
            upper = mid + std_dev * std
            lower = mid - std_dev * std

            out[f"bb_{period}_{int(std_dev)}_upper"] = float(upper)
            out[f"bb_{period}_{int(std_dev)}_mid"] = float(mid)
            out[f"bb_{period}_{int(std_dev)}_lower"] = float(lower)

        return out


plugin = BollingerPlugin()
