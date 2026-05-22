"""CMF (Chaikin Money Flow) plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full CMF via rolling MFV/volume windows
- _compute_next_core(frames, state) -> dict: single-bar rolling window update
- _seed_state(frames) -> dict: extract MFV and volume deque windows
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class CMFPlugin(IncrementalMixin):
    """Chaikin Money Flow -- windowed accumulation/distribution pressure.

    CMF = sum(MFV, period) / sum(volume, period)
    MFV = volume * (2*close - high - low) / (high - low)

    Unlike OBV (cumulative), CMF resets every N bars -- better for detecting
    short-term institutional buying/selling pressure.
    """

    name: str = "ind_CMF"
    outputs: frozenset[str] = frozenset({"cmf_20"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=60),)
    period: int = 20

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full CMF computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        hl_range = high - low
        safe_range = np.where(hl_range > 0, hl_range, 1.0)
        mfm = np.where(hl_range > 0, (2 * close - high - low) / safe_range, 0.0)
        mfv = mfm * volume

        mfv_win = mfv[-self.period :]
        vol_win = volume[-self.period :]

        vol_sum = float(np.sum(vol_win))
        cmf = float(np.sum(mfv_win)) / vol_sum if vol_sum > 0 else 0.0

        return {"cmf_20": round(cmf, 6)}

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract rolling MFV and volume windows for incremental CMF updates."""
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        hl_range = high - low
        safe_range = np.where(hl_range > 0, hl_range, 1.0)
        mfm = np.where(hl_range > 0, (2 * close - high - low) / safe_range, 0.0)
        mfv = mfm * volume

        return {
            "mfv_window": deque(mfv[-self.period :].tolist(), maxlen=self.period),
            "vol_window": deque(volume[-self.period :].tolist(), maxlen=self.period),
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental CMF update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        h = float(row["high"])
        low_price = float(row["low"])
        c = float(row["close"])
        v = float(row["volume"])

        hl = h - low_price
        mfm = (2 * c - h - low_price) / hl if hl > 0 else 0.0
        state["mfv_window"].append(mfm * v)
        state["vol_window"].append(v)

        vol_sum = sum(state["vol_window"])
        cmf = sum(state["mfv_window"]) / vol_sum if vol_sum > 0 else 0.0
        return {"cmf_20": round(cmf, 6)}


plugin = CMFPlugin()
