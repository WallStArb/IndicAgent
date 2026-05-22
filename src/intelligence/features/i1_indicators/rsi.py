"""RSI (Relative Strength Index) plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full RSI computation via Wilder's smoothing
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract Wilder's avg_gain/avg_loss from full computation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, wilders_update


@dataclass
class RSIPlugin(IncrementalMixin):
    name: str = "RSI"
    outputs: frozenset[str] = frozenset({"rsi_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"rsi_{p}" for p in self.periods})

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full RSI computation using Wilder's smoothing. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < min(self.periods) + 1:
            return {}
        close = df["close"].to_numpy(copy=False)
        out: dict[str, Any] = {}
        for p in self.periods:
            if len(close) >= p + 1:
                rsi = self._rsi_np(close, p)
                out[f"rsi_{p}"] = float(rsi[-1])
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract Wilder's smoothing state from full computation."""
        df = frames.get("main")
        if df is None:
            return {}
        close = df["close"].to_numpy(copy=False)
        state_dict: dict = {}
        for p in self.periods:
            if len(close) < p + 1:
                continue
            # Replay Wilder's smoothing to get final avg_gain/avg_loss
            deltas = np.diff(close)
            seed = deltas[:p]
            up_val = float(seed.clip(min=0).sum() / p)
            down_val = float(-seed.clip(max=0).sum() / p)
            for i in range(p, len(deltas)):
                delta = float(deltas[i])
                up_val = wilders_update(up_val, max(delta, 0), p)
                down_val = wilders_update(down_val, max(-delta, 0), p)
            state_dict[f"rsi_{p}"] = {
                "avg_gain": up_val,
                "avg_loss": down_val,
                "prev_close": float(close[-1]),
            }
        return state_dict

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental RSI update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"rsi_{p}"
            if key not in state:
                continue
            s = state[key]
            delta = close - s["prev_close"]
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            s["avg_gain"] = wilders_update(s["avg_gain"], gain, p)
            s["avg_loss"] = wilders_update(s["avg_loss"], loss, p)
            s["prev_close"] = close
            # Zero-loss guard (Renaissance: data quality over model complexity)
            # When avg_loss == 0 (no downward moves), RSI returns 100.0 (maximum momentum)
            if s["avg_loss"] == 0:
                out[key] = 100.0
            else:
                rs = s["avg_gain"] / s["avg_loss"]
                out[key] = 100.0 - 100.0 / (1.0 + rs)
        return out

    @staticmethod
    def _rsi_np(close: np.ndarray, period: int) -> np.ndarray:
        deltas = np.diff(close)
        seed = deltas[:period]
        up = seed.clip(min=0).sum() / period
        down = -seed.clip(max=0).sum() / period
        rs = up / down if down != 0 else np.inf
        rsi = np.zeros_like(close)
        rsi[:period] = 50.0
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)
        up_val = up
        down_val = down
        for i in range(period + 1, len(close)):
            delta = deltas[i - 1]
            up_val = (up_val * (period - 1) + max(delta, 0)) / period
            down_val = (down_val * (period - 1) + max(-delta, 0)) / period
            rs = up_val / down_val if down_val != 0 else np.inf
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
        return rsi


plugin = RSIPlugin()
