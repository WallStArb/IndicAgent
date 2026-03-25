from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class CCIPlugin:
    name: str = "CCI"
    outputs: frozenset[str] = frozenset({"cci_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"cci_{p}" for p in self.periods})

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None:
            return {}
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        out: dict[str, Any] = {}
        for p in self.periods:
            if len(df) < p + 1:
                continue
            # Standard Lambert CCI: MAD uses single window mean
            window = tp.iloc[-p:]
            mean_tp = float(window.mean())
            mad = float((window - mean_tp).abs().mean())
            if mad == 0:
                out[f"cci_{p}"] = 0.0
            else:
                out[f"cci_{p}"] = (float(tp.iloc[-1]) - mean_tp) / (0.015 * mad)
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract rolling typical price window for incremental CCI updates."""
        df = frames.get("main")
        if df is None:
            return
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        for p in self.periods:
            if len(df) < p + 1:
                continue
            tp_vals = tp.iloc[-p:].tolist()
            self._state[f"cci_{p}"] = {
                "tp_window": deque(tp_vals, maxlen=p),
            }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"cci_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
            s["tp_window"].append(tp)

            if len(s["tp_window"]) == p:
                tp_list = list(s["tp_window"])
                mean_tp = sum(tp_list) / p
                mad = sum(abs(x - mean_tp) for x in tp_list) / p
                if mad == 0:
                    out[key] = 0.0
                else:
                    out[key] = (tp - mean_tp) / (0.015 * mad)
        return out


plugin = CCIPlugin()
