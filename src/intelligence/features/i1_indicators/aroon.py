"""Aroon indicator plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full Aroon via numpy argmax/argmin
- _compute_next_core(frames, state) -> dict: single-bar rolling window update
- _seed_state(frames) -> dict: extract rolling high/low windows
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class AroonPlugin(IncrementalMixin):
    """Aroon indicator -- measures bars since the period high/low.

    aroon_up  = argmax(highs over period+1 bars) / period * 100
    aroon_down = argmin(lows over period+1 bars) / period * 100
    aroon_osc  = aroon_up - aroon_down  (range: -100 to +100)

    Value of 100 means the high/low was the current bar.
    Value of 0 means the high/low was exactly period bars ago.
    """

    name: str = "ind_Aroon"
    outputs: frozenset[str] = frozenset({"aroon_up_25", "aroon_down_25", "aroon_osc_25"})
    min_lookback: int = 27
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    period: int = 25

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full Aroon computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        h_win = high[-(self.period + 1) :]
        l_win = low[-(self.period + 1) :]

        aroon_up = float(np.argmax(h_win)) / self.period * 100.0
        aroon_down = float(np.argmin(l_win)) / self.period * 100.0

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract rolling high/low windows for incremental Aroon updates."""
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        h_win = high[-(self.period + 1) :]
        l_win = low[-(self.period + 1) :]

        return {
            "high_window": deque(h_win.tolist(), maxlen=self.period + 1),
            "low_window": deque(l_win.tolist(), maxlen=self.period + 1),
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental Aroon update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        state["high_window"].append(float(row["high"]))
        state["low_window"].append(float(row["low"]))

        if len(state["high_window"]) < self.period + 1:
            return {}

        hw = list(state["high_window"])
        lw = list(state["low_window"])

        aroon_up = float(np.argmax(hw)) / self.period * 100.0
        aroon_down = float(np.argmin(lw)) / self.period * 100.0

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }


plugin = AroonPlugin()
