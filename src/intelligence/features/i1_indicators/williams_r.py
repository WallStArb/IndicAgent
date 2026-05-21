"""Williams %R plugin -- migrated to IncrementalMixin.

Uses the rolling window min/max archetype (same as Stochastic):
- _compute_full_core: full Williams %R computation via rolling pandas operations
- _compute_next_core: incremental update using deque-based high/low windows
- _seed_state: extracts {high_window, low_window} deques per period

The mixin provides compute_full and compute_next -- WilliamsRPlugin defines none directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class WilliamsRPlugin(IncrementalMixin):
    """Williams %R momentum oscillator.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch Williams %R via rolling pandas operations
    - _compute_next_core: single-bar incremental update via deque rolling window
    - _seed_state: seeds {high_window, low_window} deques per period
    """

    name: str = "WilliamsR"
    outputs: frozenset[str] = frozenset({"williams_r_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"williams_r_{p}" for p in self.periods})

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute Williams %R for all periods over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {f"williams_r_{p}": float} per period. Returns {} when
            data is insufficient.
        """
        df = frames.get("main")
        if df is None:
            return {}
        high = df["high"]
        low = df["low"]
        close = df["close"]
        out: dict[str, Any] = {}
        for p in self.periods:
            if len(df) < p + 1:
                continue
            hh = high.rolling(window=p, min_periods=p).max()
            ll = low.rolling(window=p, min_periods=p).min()
            denom = (hh - ll).replace(0, pd.NA)
            wr = -100 * (hh - close) / denom
            val = wr.iloc[-1]
            out[f"williams_r_{p}"] = float(val) if pd.notna(val) else 0.0
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract rolling high/low state for incremental Williams %R updates.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with deques {high_window, low_window} per period key.
        """
        df = frames.get("main")
        if df is None:
            return {}
        state: dict[str, Any] = {}
        for p in self.periods:
            if len(df) < p + 1:
                continue
            highs = df["high"].iloc[-p:].to_numpy(copy=False)
            lows = df["low"].iloc[-p:].to_numpy(copy=False)
            state[f"wr_{p}"] = {
                "high_window": deque(highs, maxlen=p),
                "low_window": deque(lows, maxlen=p),
            }
        return state

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar Williams %R update using rolling deque windows.

        State is guaranteed non-None by the mixin. Mutates state in place.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {f"wr_{p}": {high_window,
                    low_window}} per period.

        Returns:
            Dict of {f"williams_r_{p}": float} for periods present in state.
            Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"wr_{p}"
            if key not in state:
                continue
            s = state[key]
            s["high_window"].append(high)
            s["low_window"].append(low)

            hh = max(s["high_window"])
            ll = min(s["low_window"])
            denom = hh - ll

            if denom == 0:
                out[f"williams_r_{p}"] = 0.0
            else:
                out[f"williams_r_{p}"] = -100.0 * (hh - close) / denom
        return out


plugin = WilliamsRPlugin()
