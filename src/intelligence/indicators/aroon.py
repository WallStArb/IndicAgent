from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class AroonPlugin:
    """Aroon indicator — measures bars since the period high/low.

    aroon_up  = argmax(highs over period+1 bars) / period * 100
    aroon_down = argmin(lows over period+1 bars) / period * 100
    aroon_osc  = aroon_up - aroon_down  (range: -100 to +100)

    Value of 100 means the high/low was the current bar.
    Value of 0 means the high/low was exactly period bars ago.
    """

    name: str = "ind_Aroon"
    outputs: set[str] = frozenset({"aroon_up_25", "aroon_down_25", "aroon_osc_25"})
    min_lookback: int = 27
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 25
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        # Window of (period+1) bars: oldest at index 0, current at index period
        h_win = high[-(self.period + 1):]
        l_win = low[-(self.period + 1):]

        aroon_up = float(np.argmax(h_win)) / self.period * 100.0
        aroon_down = float(np.argmin(l_win)) / self.period * 100.0

        self._state = {
            "high_window": deque(h_win.tolist(), maxlen=self.period + 1),
            "low_window": deque(l_win.tolist(), maxlen=self.period + 1),
        }

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        s = self._state
        s["high_window"].append(float(row["high"]))
        s["low_window"].append(float(row["low"]))

        if len(s["high_window"]) < self.period + 1:
            return {}

        hw = list(s["high_window"])
        lw = list(s["low_window"])

        aroon_up = float(np.argmax(hw)) / self.period * 100.0
        aroon_down = float(np.argmin(lw)) / self.period * 100.0

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }


plugin = AroonPlugin()
