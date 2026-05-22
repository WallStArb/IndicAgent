"""OBV (On-Balance Volume) plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full OBV computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract prev_close and cum_obv state
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class OBVPlugin(IncrementalMixin):
    name: str = "OBV"
    outputs: frozenset[str] = frozenset({"obv"})
    min_lookback: int = 2
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full OBV computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or not {"close", "volume"}.issubset(df.columns):
            return {}
        direction = (df["close"] > df["close"].shift(1)).astype(int) - (
            df["close"] < df["close"].shift(1)
        ).astype(int)
        obv = (direction * df["volume"]).fillna(0).cumsum()
        return {"obv": float(obv.iloc[-1])}

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract prev_close and cum_obv state for incremental seeding."""
        df = frames.get("main")
        if df is None or not {"close", "volume"}.issubset(df.columns):
            return {}
        direction = (df["close"] > df["close"].shift(1)).astype(int) - (
            df["close"] < df["close"].shift(1)
        ).astype(int)
        obv = (direction * df["volume"]).fillna(0).cumsum()
        return {
            "prev_close": float(df["close"].iloc[-1]),
            "cum_obv": float(obv.iloc[-1]),
        }

    def _compute_next_core(self, windows: dict[str, pd.DataFrame], state: dict) -> dict[str, Any]:
        """Single-bar incremental OBV update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        close = float(df["close"].iloc[-1])
        volume = float(df["volume"].iloc[-1])
        prev_close = state["prev_close"]

        if close > prev_close:
            state["cum_obv"] += volume
        elif close < prev_close:
            state["cum_obv"] -= volume

        state["prev_close"] = close
        return {"obv": state["cum_obv"]}


plugin = OBVPlugin()
