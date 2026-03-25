from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec


@dataclass
class MFIPlugin:
    name: str = "MFI"
    outputs: frozenset[str] = frozenset({"mfi_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"mfi_{p}" for p in self.periods})

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or not {"high", "low", "close", "volume"}.issubset(df.columns):
            return {}
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        rmf = tp * df["volume"]
        out: dict[str, Any] = {}
        for p in self.periods:
            if len(df) < p + 1:
                continue
            pos_mf = rmf.where(tp > tp.shift(1), 0.0)
            neg_mf = rmf.where(tp < tp.shift(1), 0.0)
            pos_sum = pos_mf.rolling(window=p, min_periods=p).sum()
            neg_sum = neg_mf.rolling(window=p, min_periods=p).sum().replace(0, pd.NA)
            mfr = pos_sum / neg_sum
            mfi = 100 - (100 / (1 + mfr))
            val = mfi.iloc[-1]
            out[f"mfi_{p}"] = float(val) if pd.notna(val) else 0.0
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract rolling money flow state for incremental MFI updates."""
        df = frames.get("main")
        if df is None or not {"high", "low", "close", "volume"}.issubset(df.columns):
            return
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        rmf = tp * df["volume"]

        for p in self.periods:
            if len(df) < p + 1:
                continue
            # Get last p+1 TPs and money flows to derive last p pos/neg flows
            tp_vals = tp.iloc[-(p + 1) :].tolist()
            rmf_vals = rmf.iloc[-(p + 1) :].tolist()

            pos_mfs = []
            neg_mfs = []
            for i in range(1, len(tp_vals)):
                if tp_vals[i] > tp_vals[i - 1]:
                    pos_mfs.append(rmf_vals[i])
                    neg_mfs.append(0.0)
                elif tp_vals[i] < tp_vals[i - 1]:
                    pos_mfs.append(0.0)
                    neg_mfs.append(rmf_vals[i])
                else:
                    pos_mfs.append(0.0)
                    neg_mfs.append(0.0)

            # Keep only last p values
            pos_mfs = pos_mfs[-p:]
            neg_mfs = neg_mfs[-p:]

            self._state[f"mfi_{p}"] = {
                "prev_tp": tp_vals[-1],
                "pos_mf_window": deque(pos_mfs, maxlen=p),
                "neg_mf_window": deque(neg_mfs, maxlen=p),
            }

    def compute_next(self, windows: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        rmf = tp * float(row["volume"])
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"mfi_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
            prev_tp = s["prev_tp"]

            if tp > prev_tp:
                s["pos_mf_window"].append(rmf)
                s["neg_mf_window"].append(0.0)
            elif tp < prev_tp:
                s["pos_mf_window"].append(0.0)
                s["neg_mf_window"].append(rmf)
            else:
                s["pos_mf_window"].append(0.0)
                s["neg_mf_window"].append(0.0)

            s["prev_tp"] = tp

            pos_sum = sum(s["pos_mf_window"])
            neg_sum = sum(s["neg_mf_window"])

            if neg_sum == 0:
                out[key] = 100.0 if pos_sum > 0 else 0.0
            else:
                mfr = pos_sum / neg_sum
                out[key] = 100.0 - 100.0 / (1.0 + mfr)
        return out


plugin = MFIPlugin()
