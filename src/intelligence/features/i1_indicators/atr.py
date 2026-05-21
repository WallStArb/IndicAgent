"""ATR (Average True Range) plugin -- reference implementation for IncrementalMixin.

This plugin demonstrates the IncrementalMixin pattern:
- _compute_full_core: pure ATR computation, returns outputs only (no _state)
- _compute_next_core: incremental Wilder's smoothing, mutates state in place
- _seed_state: extracts {prev_atr, prev_close} per period from the full computation

State ownership (MUTABLE IN-PLACE CONTRACT):
- _compute_next_core receives state dict guaranteed non-None by the mixin.
- State is mutated in place: s["prev_atr"] = new_atr; s["prev_close"] = close.
- The mixin attaches the same dict back to the output as result["_state"].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, wilders_update


@dataclass
class ATRPlugin(IncrementalMixin):
    """Average True Range indicator plugin.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch ATR via ewm (Wilder's equivalent)
    - _compute_next_core: single-bar incremental update via wilders_update
    - _seed_state: seeds {prev_atr, prev_close} per period

    The mixin's compute_full and compute_next call these methods and handle
    _state attachment and fallback logic automatically.
    """

    name: str = "ATR"
    outputs: frozenset[str] = frozenset({"atr_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"atr_{p}" for p in self.periods})

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute ATR for all periods over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {f"atr_{p}": float} for each period. Returns {} when
            data is insufficient.
        """
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
        for p in self.periods:
            atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
            val = atr.iloc[-1]
            if pd.notna(val):
                out[f"atr_{p}"] = float(val)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract incremental state from frames after full computation.

        Returns a nested state dict keyed by period: {f"atr_{p}": {"prev_atr": float,
        "prev_close": float}}. The mixin calls this after _compute_full_core succeeds
        and attaches the result as result["_state"].

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with prev_atr and prev_close per period.
        """
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
        state: dict[str, Any] = {}
        for p in self.periods:
            atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
            val = atr.iloc[-1]
            if pd.notna(val):
                state[f"atr_{p}"] = {
                    "prev_atr": float(val),
                    "prev_close": float(close.iloc[-1]),
                }
        return state

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar ATR update using Wilder's smoothing.

        State is guaranteed non-None by the mixin. Mutates state in place:
        s["prev_atr"] = new_atr; s["prev_close"] = close.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {f"atr_{p}": {"prev_atr",
                    "prev_close"}} for each active period.

        Returns:
            Dict of {f"atr_{p}": float} for periods present in state. Returns {}
            when data is insufficient.
        """
        df = frames.get("main")
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
            # Wilder's smoothing via shared utility
            new_atr = wilders_update(s["prev_atr"], tr, p)
            s["prev_atr"] = new_atr
            s["prev_close"] = close
            out[key] = new_atr
        return out


plugin = ATRPlugin()
