from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec


@dataclass
class CMFPlugin:
    """Chaikin Money Flow — windowed accumulation/distribution pressure.

    CMF = sum(MFV, period) / sum(volume, period)
    MFV = volume * (2*close - high - low) / (high - low)

    Unlike OBV (cumulative), CMF resets every N bars — better for detecting
    short-term institutional buying/selling pressure.
    """

    name: str = "ind_CMF"
    outputs: frozenset[str] = frozenset({"cmf_20"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=60),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
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

        self._state = {
            "mfv_window": deque(mfv_win.tolist(), maxlen=self.period),
            "vol_window": deque(vol_win.tolist(), maxlen=self.period),
        }
        return {"cmf_20": round(cmf, 6)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        h = float(row["high"])
        low_price = float(row["low"])
        c = float(row["close"])
        v = float(row["volume"])
        s = self._state

        hl = h - low_price
        mfm = (2 * c - h - low_price) / hl if hl > 0 else 0.0
        s["mfv_window"].append(mfm * v)
        s["vol_window"].append(v)

        vol_sum = sum(s["vol_window"])
        cmf = sum(s["mfv_window"]) / vol_sum if vol_sum > 0 else 0.0
        return {"cmf_20": round(cmf, 6)}


plugin = CMFPlugin()
