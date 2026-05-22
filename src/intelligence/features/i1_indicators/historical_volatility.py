"""HistoricalVolatility plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full HV via rolling log-return std
- _compute_next_core(frames, state) -> dict: single-bar rolling window update
- _seed_state(frames) -> dict: extract log-return and HV deque windows
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin

# 390 1m bars/day x 252 trading days/year
_ANNUALIZATION = math.sqrt(390 * 252)


@dataclass
class HistoricalVolatilityPlugin(IncrementalMixin):
    """Realized (historical) volatility: annualized std of log returns.

    hv_20      = std(log_returns, 20 bars) * sqrt(390 * 252)
    hv_ratio_20 = hv_20 / rolling_mean(hv_20, 20 bars)
                  > 1.0 -> vol elevated vs recent baseline
                  < 1.0 -> vol compressed vs recent baseline
    """

    name: str = "ind_HistoricalVolatility"
    outputs: frozenset[str] = frozenset({"hv_20", "hv_ratio_20"})
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    period: int = 20

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full HV computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        close = df["close"].to_numpy(dtype=float)
        log_returns = np.log(close[1:] / close[:-1])

        if len(log_returns) < self.period:
            return {}

        hv_values = [
            float(np.std(log_returns[i - self.period + 1 : i + 1], ddof=1) * _ANNUALIZATION)
            for i in range(self.period - 1, len(log_returns))
        ]

        hv_20 = hv_values[-1]
        recent = hv_values[-self.period :]
        hv_mean = float(np.mean(recent))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract rolling log-return and HV windows for incremental updates."""
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        close = df["close"].to_numpy(dtype=float)
        log_returns = np.log(close[1:] / close[:-1])

        if len(log_returns) < self.period:
            return {}

        hv_values = [
            float(np.std(log_returns[i - self.period + 1 : i + 1], ddof=1) * _ANNUALIZATION)
            for i in range(self.period - 1, len(log_returns))
        ]

        return {
            "prev_close": float(close[-1]),
            "log_return_window": deque(log_returns[-self.period :].tolist(), maxlen=self.period),
            "hv_window": deque(hv_values[-self.period :], maxlen=self.period),
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental HV update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        curr = float(df["close"].iloc[-1])
        state["log_return_window"].append(math.log(curr / state["prev_close"]))
        state["prev_close"] = curr

        if len(state["log_return_window"]) < self.period:
            return {}

        hv_20 = float(np.std(list(state["log_return_window"]), ddof=1) * _ANNUALIZATION)
        state["hv_window"].append(hv_20)

        hv_mean = float(np.mean(list(state["hv_window"])))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}


plugin = HistoricalVolatilityPlugin()
