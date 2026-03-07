from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class ACOscillatorPlugin:
    """
    AC Oscillator (Bill Williams) — I1 technical indicator.

    AO = SMA(5, midpoint) - SMA(34, midpoint)  where midpoint = (high + low) / 2
    AC = AO - SMA(5, AO)

    AC crosses zero before AO does, giving earlier divergence warnings.
    Pure OHLCV I1 indicator — no upstream feature dependencies.
    """

    name: str = "ind_ACOscillator"
    outputs: frozenset[str] = frozenset({"ao", "ac"})
    min_lookback: int = 40  # SMA34 + SMA5(AO) = 34 + 5 + 1 buffer
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"momentum", "oscillator"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        midpoint = (df["high"] + df["low"]) / 2
        ao = midpoint.rolling(5).mean() - midpoint.rolling(34).mean()
        ac = ao - ao.rolling(5).mean()

        ao_val = ao.iloc[-1]
        ac_val = ac.iloc[-1]

        if math.isnan(ao_val) or math.isnan(ac_val):
            return {}

        return {"ao": float(ao_val), "ac": float(ac_val)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ACOscillatorPlugin()
