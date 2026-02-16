from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class VWAPPlugin:
    name: str = "VWAP"
    outputs: set[str] = frozenset({"vwap"})
    min_lookback: int = 1
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=390),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or not {"high", "low", "close", "volume"}.issubset(df.columns):
            return {}
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        cum_pv = (tp * df["volume"]).cumsum()
        cum_v = (df["volume"]).cumsum().replace(0, pd.NA)
        vwap = cum_pv / cum_v
        result = {"vwap": float(vwap.iloc[-1])}
        # Seed state
        self._state["cum_pv"] = float(cum_pv.iloc[-1])
        self._state["cum_vol"] = float(cum_v.iloc[-1])
        return result

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        vol = float(row["volume"])
        self._state["cum_pv"] += tp * vol
        self._state["cum_vol"] += vol
        if self._state["cum_vol"] == 0:
            return {}
        return {"vwap": self._state["cum_pv"] / self._state["cum_vol"]}


plugin = VWAPPlugin()
