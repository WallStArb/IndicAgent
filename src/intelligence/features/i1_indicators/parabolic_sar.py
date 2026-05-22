"""Parabolic SAR plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full PSAR replay
- _compute_next_core(frames, state) -> dict: single-bar SAR step
- _seed_state(frames) -> dict: extract SAR state from full replay
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class PSARPlugin(IncrementalMixin):
    """Parabolic SAR -- trailing stop and reversal system.

    psar_value     : current SAR price level
    psar_direction : +1.0 (bull, SAR below price) / -1.0 (bear, SAR above price)

    A flip from +1 to -1 or vice versa signals a potential trend reversal.
    """

    name: str = "ind_ParabolicSAR"
    outputs: frozenset[str] = frozenset({"psar_value", "psar_direction"})
    min_lookback: int = 10
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=50),)
    af_step: float = 0.02
    af_max: float = 0.20

    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Full PSAR computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        _, sar, direction = self._replay_psar(high, low)

        return {"psar_value": sar, "psar_direction": direction}

    def _seed_state(self, frames: dict[str, Any]) -> dict:
        """Extract PSAR state from full replay for incremental updates."""
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        state, _, _ = self._replay_psar(high, low)
        return state

    def _replay_psar(self, high: np.ndarray, low: np.ndarray) -> tuple[dict, float, float]:
        """Replay full PSAR over arrays. Returns (state_dict, sar, direction)."""
        n = len(high)
        init = min(5, n // 2)
        if high[init - 1] >= high[0]:
            direction = 1.0
            ep = float(np.max(high[:init]))
            sar = float(np.min(low[:init]))
        else:
            direction = -1.0
            ep = float(np.min(low[:init]))
            sar = float(np.max(high[:init]))

        af = self.af_step
        prev_prev_h = float(high[max(0, init - 2)])
        prev_prev_l = float(low[max(0, init - 2)])
        prev_h = float(high[init - 1])
        prev_l = float(low[init - 1])

        for i in range(init, n):
            curr_h = float(high[i])
            curr_l = float(low[i])

            if direction == 1.0:
                new_sar = sar + af * (ep - sar)
                new_sar = min(new_sar, prev_l, prev_prev_l)
                if curr_l < new_sar:
                    direction = -1.0
                    new_sar = ep
                    ep = curr_l
                    af = self.af_step
                else:
                    if curr_h > ep:
                        ep = curr_h
                        af = min(af + self.af_step, self.af_max)
            else:
                new_sar = sar + af * (ep - sar)
                new_sar = max(new_sar, prev_h, prev_prev_h)
                if curr_h > new_sar:
                    direction = 1.0
                    new_sar = ep
                    ep = curr_h
                    af = self.af_step
                else:
                    if curr_l < ep:
                        ep = curr_l
                        af = min(af + self.af_step, self.af_max)

            prev_prev_h = prev_h
            prev_prev_l = prev_l
            prev_h = curr_h
            prev_l = curr_l
            sar = new_sar

        state = {
            "sar": sar,
            "ep": ep,
            "af": af,
            "direction": direction,
            "prev_high": prev_h,
            "prev_low": prev_l,
            "prev_prev_high": prev_prev_h,
            "prev_prev_low": prev_prev_l,
        }
        return state, sar, direction

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental PSAR update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        curr_h = float(row["high"])
        curr_l = float(row["low"])

        if state["direction"] == 1.0:
            new_sar = state["sar"] + state["af"] * (state["ep"] - state["sar"])
            new_sar = min(new_sar, state["prev_low"], state["prev_prev_low"])
            if curr_l < new_sar:
                state["direction"] = -1.0
                new_sar = state["ep"]
                state["ep"] = curr_l
                state["af"] = self.af_step
            else:
                if curr_h > state["ep"]:
                    state["ep"] = curr_h
                    state["af"] = min(state["af"] + self.af_step, self.af_max)
        else:
            new_sar = state["sar"] + state["af"] * (state["ep"] - state["sar"])
            new_sar = max(new_sar, state["prev_high"], state["prev_prev_high"])
            if curr_h > new_sar:
                state["direction"] = 1.0
                new_sar = state["ep"]
                state["ep"] = curr_h
                state["af"] = self.af_step
            else:
                if curr_l < state["ep"]:
                    state["ep"] = curr_l
                    state["af"] = min(state["af"] + self.af_step, self.af_max)

        state["prev_prev_high"] = state["prev_high"]
        state["prev_prev_low"] = state["prev_low"]
        state["prev_high"] = curr_h
        state["prev_low"] = curr_l
        state["sar"] = new_sar

        return {"psar_value": new_sar, "psar_direction": state["direction"]}


plugin = PSARPlugin()
