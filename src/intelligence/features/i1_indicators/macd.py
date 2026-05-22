"""MACD (Moving Average Convergence Divergence) plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full MACD computation via pandas EWM
- _compute_next_core(frames, state) -> dict: single-bar EMA update
- _seed_state(frames) -> dict: extract final EMA values for incremental seeding
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, get_main_df, update_ema


@dataclass
class MACDPlugin(IncrementalMixin):
    name: str = "MACD"
    outputs: frozenset[str] = frozenset(
        {"macd_12_26_9", "macd_signal_12_26_9", "macd_histogram_12_26_9"}
    )
    min_lookback: int = 50
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=200),)
    configs: list[tuple] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.configs:
            self.configs = [(12, 26, 9)]
        self.outputs = frozenset(
            {
                key
                for (f, s, sig) in self.configs
                for key in (
                    f"macd_{f}_{s}_{sig}",
                    f"macd_signal_{f}_{s}_{sig}",
                    f"macd_histogram_{f}_{s}_{sig}",
                )
            }
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full MACD computation using pandas EWM. Returns outputs only (no _state)."""
        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}
        for fast, slow, signal in self.configs:
            if len(close) < slow + signal + 1:
                continue
            ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
            ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
            macd_line = ema_fast - ema_slow
            macd_signal = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
            macd_hist = macd_line - macd_signal
            out[f"macd_{fast}_{slow}_{signal}"] = float(macd_line.iloc[-1])
            out[f"macd_signal_{fast}_{slow}_{signal}"] = float(macd_signal.iloc[-1])
            out[f"macd_histogram_{fast}_{slow}_{signal}"] = float(macd_hist.iloc[-1])
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract EMA state for incremental MACD updates."""
        df = get_main_df(frames, 1)
        if df is None:
            return {}
        close = df["close"]
        state: dict = {}
        for fast, slow, signal in self.configs:
            if len(close) < slow + signal + 1:
                continue
            ema_fast_series = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
            ema_slow_series = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
            macd_line = ema_fast_series - ema_slow_series
            macd_signal_series = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()

            key = f"macd_{fast}_{slow}_{signal}"
            state[key] = {
                "ema_fast": float(ema_fast_series.iloc[-1]),
                "ema_slow": float(ema_slow_series.iloc[-1]),
                "ema_signal": float(macd_signal_series.iloc[-1]),
            }
        return state

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental MACD update. Mutates state in place."""
        df = get_main_df(windows, 1)
        if df is None:
            return {}
        new_close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for fast, slow, signal in self.configs:
            key = f"macd_{fast}_{slow}_{signal}"
            if key not in state:
                continue
            s = state[key]
            # Update fast EMA
            s["ema_fast"] = update_ema(new_close, s["ema_fast"], fast)
            # Update slow EMA
            s["ema_slow"] = update_ema(new_close, s["ema_slow"], slow)
            # MACD line
            macd_val = s["ema_fast"] - s["ema_slow"]
            # Update signal EMA
            s["ema_signal"] = update_ema(macd_val, s["ema_signal"], signal)
            # Histogram
            histogram = macd_val - s["ema_signal"]

            out[f"macd_{fast}_{slow}_{signal}"] = macd_val
            out[f"macd_signal_{fast}_{slow}_{signal}"] = s["ema_signal"]
            out[f"macd_histogram_{fast}_{slow}_{signal}"] = histogram
        return out


plugin = MACDPlugin()
