"""OBVMomentum — bridge composite for On-Balance Volume direction.

Computes OBV from raw bars, runs linear regression over a rolling window,
and emits the slope sign as +1 (accumulation) / 0 (neutral) / -1 (distribution).
Feeds into CIS institutional bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec, PatternPlugin

_WINDOW = 10  # bars for slope regression


@dataclass
class OBVMomentumPlugin(PatternPlugin):
    name: str = "evt_OBVMomentum"
    outputs: frozenset[str] = field(default_factory=lambda: frozenset({"obv_slope_sign"}))
    min_lookback: int = _WINDOW + 1
    capability_tags: frozenset[str] = field(
        default_factory=lambda: frozenset({"volume", "momentum"})
    )
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=_WINDOW + 5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {"obv_slope_sign": 0}

        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        # Compute OBV
        obv = np.zeros(len(close))
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]

        # Linear regression slope over last _WINDOW bars
        window = obv[-_WINDOW:]
        x = np.arange(len(window), dtype=float)
        slope = float(np.polyfit(x, window, 1)[0])

        sign = 1 if slope > 0 else (-1 if slope < 0 else 0)
        return {"obv_slope_sign": sign}


plugin = OBVMomentumPlugin()
