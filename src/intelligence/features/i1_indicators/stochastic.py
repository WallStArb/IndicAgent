"""Stochastic oscillator plugin -- migrated to IncrementalMixin.

Uses the rolling window min/max archetype:
- _compute_full_core: full Stochastic computation via rolling pandas operations
- _compute_next_core: incremental update using deque-based high/low windows
- _seed_state: extracts {high_window, low_window, k_values} deques per config

The mixin provides compute_full and compute_next -- StochasticPlugin defines none directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class StochasticPlugin(IncrementalMixin):
    """Stochastic oscillator (%K and %D lines).

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch Stochastic via rolling pandas operations
    - _compute_next_core: single-bar incremental update via deque rolling window
    - _seed_state: seeds {high_window, low_window, k_values} deques per config
    """

    name: str = "Stochastic"
    outputs: frozenset[str] = frozenset({"stoch_k_14_3", "stoch_d_14_3"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    configs: list[tuple[int, int]] = None

    def __post_init__(self) -> None:
        if not self.configs:
            self.configs = [(14, 3)]
        self.outputs = frozenset(
            {key for (k, d) in self.configs for key in (f"stoch_k_{k}_{d}", f"stoch_d_{k}_{d}")}
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute Stochastic for all configs over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {f"stoch_k_{k}_{d}": float, f"stoch_d_{k}_{d}": float} per config.
            Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) == 0:
            return {}
        # Convert once to float64 Series to avoid pandas 3.x dtype inference issues
        high_series = pd.Series(df["high"].to_numpy(copy=False), dtype="float64")
        low_series = pd.Series(df["low"].to_numpy(copy=False), dtype="float64")
        close_series = pd.Series(df["close"].to_numpy(copy=False), dtype="float64")
        out: dict[str, Any] = {}
        for k_period, d_period in self.configs:
            if len(df) < k_period + d_period:
                continue

            lowest_low = low_series.rolling(window=k_period, min_periods=k_period).min()
            highest_high = high_series.rolling(window=k_period, min_periods=k_period).max()
            denom = (highest_high - lowest_low).replace(0, np.nan)
            k = 100 * (close_series - lowest_low) / denom
            d = k.rolling(window=d_period, min_periods=d_period).mean()
            out[f"stoch_k_{k_period}_{d_period}"] = (
                float(k.iloc[-1]) if pd.notna(k.iloc[-1]) else 0.0
            )
            out[f"stoch_d_{k_period}_{d_period}"] = (
                float(d.iloc[-1]) if pd.notna(d.iloc[-1]) else 0.0
            )
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract rolling high/low/K state for incremental Stochastic updates.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with deques {high_window, low_window, k_values} per config key.
        """
        df = frames.get("main")
        if df is None or len(df) == 0:
            return {}
        high_col = pd.Series(df["high"].to_numpy(copy=False), dtype="float64")
        low_col = pd.Series(df["low"].to_numpy(copy=False), dtype="float64")
        close_col = pd.Series(df["close"].to_numpy(copy=False), dtype="float64")
        n = len(high_col)
        state: dict[str, Any] = {}
        for k_period, d_period in self.configs:
            if n < k_period + d_period:
                continue
            # Keep last k_period highs and lows for rolling min/max
            highs = high_col.iloc[-k_period:].to_numpy(copy=False)
            lows = low_col.iloc[-k_period:].to_numpy(copy=False)

            # Compute last d_period %K values for %D SMA
            lowest_low = low_col.rolling(window=k_period, min_periods=k_period).min()
            highest_high = high_col.rolling(window=k_period, min_periods=k_period).max()
            denom = (highest_high - lowest_low).replace(0, np.nan)
            k_series = 100 * (close_col - lowest_low) / denom
            k_raw = k_series.iloc[-d_period:].to_numpy(copy=False)
            k_vals = [float(v) if not np.isnan(v) else 0.0 for v in k_raw]

            key = f"stoch_{k_period}_{d_period}"
            state[key] = {
                "high_window": deque(highs, maxlen=k_period),
                "low_window": deque(lows, maxlen=k_period),
                "k_values": deque(k_vals, maxlen=d_period),
            }
        return state

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar Stochastic update using rolling deque windows.

        State is guaranteed non-None by the mixin. Mutates state in place.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {f"stoch_{k}_{d}": {high_window,
                    low_window, k_values}} per config.

        Returns:
            Dict of {f"stoch_k_{k}_{d}": float, f"stoch_d_{k}_{d}": float} for configs
            present in state. Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        out: dict[str, Any] = {}
        for k_period, d_period in self.configs:
            key = f"stoch_{k_period}_{d_period}"
            if key not in state:
                continue
            s = state[key]
            s["high_window"].append(high)
            s["low_window"].append(low)

            highest_high = max(s["high_window"])
            lowest_low = min(s["low_window"])
            denom = highest_high - lowest_low

            k_val = 100.0 * (close - lowest_low) / denom if denom != 0 else 0.0
            s["k_values"].append(k_val)
            d_val = sum(s["k_values"]) / len(s["k_values"]) if s["k_values"] else 0.0

            out[f"stoch_k_{k_period}_{d_period}"] = k_val
            out[f"stoch_d_{k_period}_{d_period}"] = d_val
        return out


plugin = StochasticPlugin()
