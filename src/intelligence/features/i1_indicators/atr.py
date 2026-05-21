from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class ATRPlugin:
    name: str = "ATR"
    outputs: frozenset[str] = frozenset({"atr_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] = None

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"atr_{p}" for p in self.periods})

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < min(self.periods) + 1:
            return {}
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out: dict[str, Any] = {}
        state = {}
        for p in self.periods:
            atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
            val = atr.iloc[-1]
            if pd.notna(val):
                out[f"atr_{p}"] = float(val)
                state[f"atr_{p}"] = {
                    "prev_atr": float(val),
                    "prev_close": float(close.iloc[-1]),
                }
        out["_state"] = state
        return out

    def compute_next(
        self, windows: dict[str, pd.DataFrame], *, state: dict | None = None
    ) -> dict[str, Any]:
        if not state:
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
            key = f"atr_{p}"
            if key not in state:
                continue
            s = state[key]
            # True Range
            hl = abs(high - low)
            hc = abs(high - s["prev_close"])
            lc = abs(low - s["prev_close"])
            tr = max(hl, hc, lc)
            # Wilder's smoothing: ewm(alpha=1/p)
            alpha = 1.0 / p
            new_atr = (1 - alpha) * s["prev_atr"] + alpha * tr
            s["prev_atr"] = new_atr
            s["prev_close"] = close
            out[key] = new_atr
        out["_state"] = state
        return out


plugin = ATRPlugin()
