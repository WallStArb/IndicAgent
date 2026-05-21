from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import get_main_df


@dataclass
class ACOscillatorPlugin:
    """
    AC Oscillator (Bill Williams) -- I1 technical indicator.

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
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
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

        # Seed incremental state
        self._seed_state(midpoint, ao_series)

        return {"ao": float(ao_val), "ac": float(ac_val), "_state": self._state}

    def _seed_state(self, midpoint_series: Any, ao_series: Any) -> None:
        """Seed rolling window state for incremental updates."""
        n = len(midpoint_series)
        if n < 34:
            return

        # SMA(5, midpoint): keep last 5 midpoints + running sum
        mp5_window = midpoint_series.iloc[-5:].tolist()
        mp5_sum = sum(mp5_window)

        # SMA(34, midpoint): keep last 34 midpoints + running sum
        mp34_window = midpoint_series.iloc[-34:].tolist()
        mp34_sum = sum(mp34_window)

        # Last 5 AO values (for SMA5 of AO)
        # Drop NaN values at the front of ao_series
        ao_clean = ao_series.dropna()
        if len(ao_clean) < 5:
            return
        ao5_window = ao_clean.iloc[-5:].tolist()
        ao5_sum = sum(ao5_window)

        self._state = {
            "mp5_window": deque(mp5_window, maxlen=5),
            "mp5_sum": mp5_sum,
            "mp34_window": deque(mp34_window, maxlen=34),
            "mp34_sum": mp34_sum,
            "ao5_window": deque(ao5_window, maxlen=5),
            "ao5_sum": ao5_sum,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)

        df = get_main_df(windows, 1)
        if df is None:
            return {}

        bar = df.iloc[-1]
        midpoint = (float(bar["high"]) + float(bar["low"])) / 2.0

        s = self._state

        # Update SMA34(midpoint)
        mp34_window = s["mp34_window"]
        if len(mp34_window) == 34:
            s["mp34_sum"] -= mp34_window[0]
        mp34_window.append(midpoint)
        s["mp34_sum"] += midpoint

        # Update SMA5(midpoint)
        mp5_window = s["mp5_window"]
        if len(mp5_window) == 5:
            s["mp5_sum"] -= mp5_window[0]
        mp5_window.append(midpoint)
        s["mp5_sum"] += midpoint

        if len(mp34_window) < 34 or len(mp5_window) < 5:
            return {}

        # AO = SMA5(midpoint) - SMA34(midpoint)
        ao = s["mp5_sum"] / 5.0 - s["mp34_sum"] / 34.0

        # Update SMA5(AO)
        ao5_window = s["ao5_window"]
        if len(ao5_window) == 5:
            s["ao5_sum"] -= ao5_window[0]
        ao5_window.append(ao)
        s["ao5_sum"] += ao

        if len(ao5_window) < 5:
            return {}

        # AC = AO - SMA5(AO)
        ac = ao - s["ao5_sum"] / 5.0

        return {"ao": float(ao), "ac": float(ac)}


plugin = ACOscillatorPlugin()
