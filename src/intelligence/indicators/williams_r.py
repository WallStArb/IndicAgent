from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class WilliamsRPlugin:
    name: str = "WilliamsR"
    outputs: frozenset[str] = frozenset({"williams_r_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"williams_r_{p}" for p in self.periods})

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
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
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract rolling high/low state for incremental Williams %R updates."""
        df = frames.get("main")
        if df is None:
            return
        for p in self.periods:
            if len(df) < p + 1:
                continue
            highs = df["high"].iloc[-p:].tolist()
            lows = df["low"].iloc[-p:].tolist()
            self._state[f"wr_{p}"] = {
                "high_window": deque(highs, maxlen=p),
                "low_window": deque(lows, maxlen=p),
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
        for p in self.periods:
            key = f"wr_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
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
