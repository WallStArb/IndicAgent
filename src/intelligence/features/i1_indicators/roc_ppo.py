"""ROC/PPO plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full ROC + PPO via pandas EWM
- _compute_next_core(frames, state) -> dict: single-bar EMA + ROC window update
- _seed_state(frames) -> dict: extract EMA values and ROC deque
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, get_main_df, update_ema


@dataclass
class ROCPPOPlugin(IncrementalMixin):
    """Rate of Change (ROC) and Percentage Price Oscillator (PPO).

    ROC: ((close - close_n) / close_n) * 100  (simple % change over N periods)
    PPO: ((EMA_fast - EMA_slow) / EMA_slow) * 100  (normalized MACD)

    PPO is MACD expressed as a percentage, enabling cross-instrument comparison.
    """

    name: str = "ROC_PPO"
    outputs: frozenset[str] = frozenset({"roc_14", "ppo_12_26", "ppo_signal_12_26"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)
    roc_period: int = 14
    ppo_fast: int = 12
    ppo_slow: int = 26
    ppo_signal: int = 9
    configs: list | None = field(default=None)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"roc_{self.roc_period}",
                f"ppo_{self.ppo_fast}_{self.ppo_slow}",
                f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}",
            }
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full ROC + PPO computation. Returns outputs only (no _state)."""
        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}

        if len(close) > self.roc_period:
            current = float(close.iloc[-1])
            past = float(close.iloc[-1 - self.roc_period])
            out[f"roc_{self.roc_period}"] = 100.0 * (current - past) / past if past != 0 else 0.0

        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(
            span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal
        ).mean()

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_line.iloc[-1])
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_sig.iloc[-1])
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract EMA values and ROC window for incremental updates."""
        df = get_main_df(frames, 1)
        if df is None:
            return {}
        close = df["close"]

        recent = close.iloc[-self.roc_period - 1 :].tolist()
        roc_window = deque(recent, maxlen=self.roc_period + 1)

        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(
            span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal
        ).mean()

        ema_fast_val = float(ema_fast.iloc[-1])
        ema_slow_val = float(ema_slow.iloc[-1])
        ppo_sig_val = float(ppo_sig.iloc[-1])
        if math.isnan(ema_fast_val) or math.isnan(ema_slow_val) or math.isnan(ppo_sig_val):
            return {}

        return {
            "roc_window": roc_window,
            "ema_fast": ema_fast_val,
            "ema_slow": ema_slow_val,
            "ppo_signal_ema": ppo_sig_val,
        }

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental ROC + PPO update. Mutates state in place."""
        df = get_main_df(windows, 1)
        if df is None:
            return {}
        c = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}

        state["roc_window"].append(c)
        if len(state["roc_window"]) == self.roc_period + 1:
            past = state["roc_window"][0]
            out[f"roc_{self.roc_period}"] = 100.0 * (c - past) / past if past != 0 else 0.0

        state["ema_fast"] = update_ema(c, state["ema_fast"], self.ppo_fast)
        state["ema_slow"] = update_ema(c, state["ema_slow"], self.ppo_slow)

        ppo_val = (
            100.0 * (state["ema_fast"] - state["ema_slow"]) / state["ema_slow"]
            if state["ema_slow"] != 0
            else 0.0
        )

        state["ppo_signal_ema"] = update_ema(ppo_val, state["ppo_signal_ema"], self.ppo_signal)

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = ppo_val
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = state["ppo_signal_ema"]
        return out


plugin = ROCPPOPlugin()
