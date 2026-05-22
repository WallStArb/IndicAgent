"""Moving Averages plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full SMA/EMA computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract rolling window + EMA state
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, get_main_df


@dataclass
class MovingAveragesPlugin(IncrementalMixin):
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
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)

    sma_periods: list[int] = field(default_factory=lambda: [20, 50, 100, 200])
    ema_periods: list[int] = field(default_factory=lambda: [8, 9, 13, 21, 55])

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full SMA/EMA computation. Returns outputs only (no _state)."""
        df = get_main_df(frames, self.min_lookback)
        if df is None:
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

        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract rolling window and EMA state for incremental updates."""
        df = get_main_df(frames, 1)
        if df is None:
            return {}
        close = df["close"]
        state: dict = {}

        # SMA: keep rolling window + running sum
        for p in self.sma_periods:
            if len(close) < p:
                continue
            window_data = close.iloc[-p:].tolist()
            state[f"sma_{p}"] = {
                "window": deque(window_data, maxlen=p),
                "sum": sum(window_data),
            }

        # EMA: keep last value
        for p in self.ema_periods:
            if len(close) < p:
                continue
            ema_val = close.ewm(span=p, adjust=False, min_periods=p).mean().iloc[-1]
            if pd.notna(ema_val):
                state[f"ema_{p}"] = float(ema_val)

        return state

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental SMA/EMA update. Mutates state in place."""
        df = get_main_df(windows, 1)
        if df is None:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}

        # SMA incremental: sliding window with running sum
        for p in self.sma_periods:
            key = f"sma_{p}"
            if key not in state:
                continue
            s = state[key]
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
            if key not in state:
                continue
            alpha = 2.0 / (p + 1)
            new_ema = alpha * new_close + (1 - alpha) * state[key]
            state[key] = new_ema
            out[key] = new_ema

        return out


plugin = MovingAveragesPlugin()
