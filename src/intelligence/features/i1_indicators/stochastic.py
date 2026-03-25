from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class StochasticPlugin:
    name: str = "Stochastic"
    outputs: frozenset[str] = frozenset({"stoch_k_14_3", "stoch_d_14_3"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    configs: list[tuple[int, int]] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.configs:
            self.configs = [(14, 3)]
        self.outputs = frozenset(
            {key for (k, d) in self.configs for key in (f"stoch_k_{k}_{d}", f"stoch_d_{k}_{d}")}
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) == 0:
            return {}
        # Convert to numpy arrays first to avoid pandas 3.x "No numeric types to aggregate" errors
        # when Series has object dtype (can happen even with numeric values)
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
        self._seed_state(high_series, low_series, close_series)
        return out

    def _seed_state(
        self,
        high_col: pd.Series,
        low_col: pd.Series,
        close_col: pd.Series,
    ) -> None:
        """Extract rolling high/low/K state for incremental Stochastic updates."""
        n = len(high_col)
        for k_period, d_period in self.configs:
            if n < k_period + d_period:
                continue
            # Keep last k_period highs and lows for rolling min/max
            highs = high_col.iloc[-k_period:].tolist()
            lows = low_col.iloc[-k_period:].tolist()

            # Compute last d_period %K values for %D SMA
            lowest_low = low_col.rolling(window=k_period, min_periods=k_period).min()
            highest_high = high_col.rolling(window=k_period, min_periods=k_period).max()
            denom = (highest_high - lowest_low).replace(0, np.nan)
            k_series = 100 * (close_col - lowest_low) / denom
            k_vals = k_series.iloc[-d_period:].tolist()
            k_vals = [v if pd.notna(v) else 0.0 for v in k_vals]

            key = f"stoch_{k_period}_{d_period}"
            self._state[key] = {
                "high_window": deque(highs, maxlen=k_period),
                "low_window": deque(lows, maxlen=k_period),
                "k_values": deque(k_vals, maxlen=d_period),
            }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        out: dict[str, Any] = {}
        for k_period, d_period in self.configs:
            key = f"stoch_{k_period}_{d_period}"
            if key not in self._state:
                continue
            s = self._state[key]
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
