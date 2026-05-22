"""AC Oscillator plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full AC/AO via pandas rolling SMA
- _compute_next_core(frames, state) -> dict: single-bar rolling sum update
- _seed_state(frames) -> dict: extract midpoint and AO deque windows
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, get_main_df


@dataclass
class ACOscillatorPlugin(IncrementalMixin):
    """AC Oscillator (Bill Williams) -- I1 technical indicator.

    AO = SMA(5, midpoint) - SMA(34, midpoint)  where midpoint = (high + low) / 2
    AC = AO - SMA(5, AO)

    AC crosses zero before AO does, giving earlier divergence warnings.
    Pure OHLCV I1 indicator -- no upstream feature dependencies.
    """

    name: str = "ind_ACOscillator"
    outputs: frozenset[str] = frozenset({"ao", "ac"})
    min_lookback: int = 40  # SMA34 + SMA5(AO) = 34 + 5 + 1 buffer
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum", "oscillator"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full AC/AO computation. Returns outputs only (no _state)."""
        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}

        midpoint = (df["high"] + df["low"]) / 2
        ao_series = midpoint.rolling(5).mean() - midpoint.rolling(34).mean()
        ac_series = ao_series - ao_series.rolling(5).mean()

        ao_val = ao_series.iloc[-1]
        ac_val = ac_series.iloc[-1]

        if math.isnan(ao_val) or math.isnan(ac_val):
            return {}

        return {"ao": float(ao_val), "ac": float(ac_val)}

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract rolling midpoint and AO windows for incremental AC updates."""
        df = get_main_df(frames, self.min_lookback)
        if df is None:
            return {}

        midpoint = (df["high"] + df["low"]) / 2
        ao_series = midpoint.rolling(5).mean() - midpoint.rolling(34).mean()

        n = len(midpoint)
        if n < 34:
            return {}

        mp5_window = midpoint.iloc[-5:].tolist()
        mp5_sum = sum(mp5_window)

        mp34_window = midpoint.iloc[-34:].tolist()
        mp34_sum = sum(mp34_window)

        ao_clean = ao_series.dropna()
        if len(ao_clean) < 5:
            return {}
        ao5_window = ao_clean.iloc[-5:].tolist()
        ao5_sum = sum(ao5_window)

        return {
            "mp5_window": deque(mp5_window, maxlen=5),
            "mp5_sum": mp5_sum,
            "mp34_window": deque(mp34_window, maxlen=34),
            "mp34_sum": mp34_sum,
            "ao5_window": deque(ao5_window, maxlen=5),
            "ao5_sum": ao5_sum,
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental AC update. Mutates state in place."""
        df = get_main_df(windows, 1)
        if df is None:
            return {}

        bar = df.iloc[-1]
        midpoint = (float(bar["high"]) + float(bar["low"])) / 2.0

        mp34_window = state["mp34_window"]
        if len(mp34_window) == 34:
            state["mp34_sum"] -= mp34_window[0]
        mp34_window.append(midpoint)
        state["mp34_sum"] += midpoint

        mp5_window = state["mp5_window"]
        if len(mp5_window) == 5:
            state["mp5_sum"] -= mp5_window[0]
        mp5_window.append(midpoint)
        state["mp5_sum"] += midpoint

        if len(mp34_window) < 34 or len(mp5_window) < 5:
            return {}

        ao = state["mp5_sum"] / 5.0 - state["mp34_sum"] / 34.0

        ao5_window = state["ao5_window"]
        if len(ao5_window) == 5:
            state["ao5_sum"] -= ao5_window[0]
        ao5_window.append(ao)
        state["ao5_sum"] += ao

        if len(ao5_window) < 5:
            return {}

        ac = ao - state["ao5_sum"] / 5.0
        return {"ao": float(ao), "ac": float(ac)}


plugin = ACOscillatorPlugin()
