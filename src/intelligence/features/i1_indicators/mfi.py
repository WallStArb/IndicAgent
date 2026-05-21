"""Money Flow Index (MFI) plugin -- migrated to IncrementalMixin.

Uses the windowed money flow deque archetype:
- _compute_full_core: full MFI computation via rolling pandas operations
- _compute_next_core: incremental update using deque-based money flow windows
- _seed_state: extracts {prev_tp, pos_mf_window, neg_mf_window} deques per period

Phase 093 fix preserved: all-positive money flow returns 100.0 (not 0.0).

The mixin provides compute_full and compute_next -- MFIPlugin defines none directly.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class MFIPlugin(IncrementalMixin):
    """Money Flow Index -- volume-weighted RSI variant.

    Uses IncrementalMixin to own the state contract. Implements:
    - _compute_full_core: batch MFI via rolling pandas operations
    - _compute_next_core: single-bar incremental update via deque money flow windows
    - _seed_state: seeds {prev_tp, pos_mf_window, neg_mf_window} deques per period

    Phase 093 bug fix preserved: when neg_sum == 0 and pos_sum > 0, returns 100.0
    (all-positive money flow). Without this fix, the original code returned 0.0.
    """

    name: str = "MFI"
    outputs: frozenset[str] = frozenset({"mfi_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"mfi_{p}" for p in self.periods})

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Compute MFI for all periods over full history.

        Returns output values only -- no _state key. The mixin calls
        _seed_state separately to attach state.

        Returns:
            Dict of {f"mfi_{p}": float} per period. Returns {} when data is insufficient.
        """
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
            ps = float(pos_mf.iloc[-p:].sum(min_count=p))
            ns = float(neg_mf.iloc[-p:].sum(min_count=p))
            if pd.isna(ps) or pd.isna(ns):
                continue
            # Phase 093 bug fix: all-positive money flow returns 100.0 (not 0.0)
            if ns == 0:
                out[f"mfi_{p}"] = 100.0 if ps > 0 else 0.0
            else:
                out[f"mfi_{p}"] = 100.0 - 100.0 / (1.0 + ps / ns)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Extract rolling money flow state for incremental MFI updates.

        Args:
            frames: Same frames dict passed to _compute_full_core.

        Returns:
            State dict with {prev_tp, pos_mf_window, neg_mf_window} deques per period.
        """
        df = frames.get("main")
        if df is None or not {"high", "low", "close", "volume"}.issubset(df.columns):
            return {}
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        rmf = tp * df["volume"]
        state: dict[str, Any] = {}
        for p in self.periods:
            if len(df) < p + 1:
                continue
            # Get last p+1 TPs and money flows to derive last p pos/neg flows
            tp_vals = tp.iloc[-(p + 1) :].to_numpy(copy=False)
            rmf_vals = rmf.iloc[-(p + 1) :].to_numpy(copy=False)

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

            state[f"mfi_{p}"] = {
                "prev_tp": tp_vals[-1],
                "pos_mf_window": deque(pos_mfs, maxlen=p),
                "neg_mf_window": deque(neg_mfs, maxlen=p),
            }
        return state

    def _compute_next_core(
        self, frames: dict[str, pd.DataFrame], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Incremental single-bar MFI update using rolling money flow deques.

        State is guaranteed non-None by the mixin. Mutates state in place.
        Preserves Phase 093 fix: neg_sum == 0 and pos_sum > 0 returns 100.0.

        Args:
            frames: Plugin frames dict. Executor passes full historical frames.
            state:  Mutable state dict. Expected keys: {f"mfi_{p}": {prev_tp,
                    pos_mf_window, neg_mf_window}} per period.

        Returns:
            Dict of {f"mfi_{p}": float} for periods present in state.
            Returns {} when data is insufficient.
        """
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        tp = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
        rmf = tp * float(row["volume"])
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"mfi_{p}"
            if key not in state:
                continue
            s = state[key]
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

            # Phase 093 bug fix: all-positive money flow returns 100.0 (not 0.0)
            if neg_sum == 0:
                out[key] = 100.0 if pos_sum > 0 else 0.0
            else:
                mfr = pos_sum / neg_sum
                out[key] = 100.0 - 100.0 / (1.0 + mfr)
        return out


plugin = MFIPlugin()
