from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class OBVPlugin:
    name: str = "OBV"
    outputs: set[str] = frozenset({"obv"})
    min_lookback: int = 2
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or not {"close", "volume"}.issubset(df.columns):
            return {}
        direction = (df["close"] > df["close"].shift(1)).astype(int) - (
            df["close"] < df["close"].shift(1)
        ).astype(int)
        obv = (direction * df["volume"]).fillna(0).cumsum()
        result = {"obv": float(obv.iloc[-1])}
        # Seed state for incremental updates
        self._state["prev_close"] = float(df["close"].iloc[-1])
        self._state["cum_obv"] = float(obv.iloc[-1])
        return result

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        close = float(df["close"].iloc[-1])
        volume = float(df["volume"].iloc[-1])
        prev_close = self._state["prev_close"]

        if close > prev_close:
            self._state["cum_obv"] += volume
        elif close < prev_close:
            self._state["cum_obv"] -= volume

        self._state["prev_close"] = close
        return {"obv": self._state["cum_obv"]}


plugin = OBVPlugin()
