from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class PSARPlugin:
    """Parabolic SAR — trailing stop and reversal system.

    psar_value     : current SAR price level
    psar_direction : +1.0 (bull, SAR below price) / -1.0 (bear, SAR above price)

    A flip from +1 to -1 or vice versa signals a potential trend reversal.
    """

    name: str = "ind_ParabolicSAR"
    outputs: set[str] = frozenset({"psar_value", "psar_direction"})
    min_lookback: int = 10
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=50),)
    af_step: float = 0.02
    af_max: float = 0.20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        n = len(high)

        # Initialize from first 5 bars
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

        self._state = {
            "sar": sar,
            "ep": ep,
            "af": af,
            "direction": direction,
            "prev_high": prev_h,
            "prev_low": prev_l,
            "prev_prev_high": prev_prev_h,
            "prev_prev_low": prev_prev_l,
        }
        return {"psar_value": sar, "psar_direction": direction}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        curr_h = float(row["high"])
        curr_l = float(row["low"])
        s = self._state

        if s["direction"] == 1.0:
            new_sar = s["sar"] + s["af"] * (s["ep"] - s["sar"])
            new_sar = min(new_sar, s["prev_low"], s["prev_prev_low"])
            if curr_l < new_sar:
                s["direction"] = -1.0
                new_sar = s["ep"]
                s["ep"] = curr_l
                s["af"] = self.af_step
            else:
                if curr_h > s["ep"]:
                    s["ep"] = curr_h
                    s["af"] = min(s["af"] + self.af_step, self.af_max)
        else:
            new_sar = s["sar"] + s["af"] * (s["ep"] - s["sar"])
            new_sar = max(new_sar, s["prev_high"], s["prev_prev_high"])
            if curr_h > new_sar:
                s["direction"] = 1.0
                new_sar = s["ep"]
                s["ep"] = curr_h
                s["af"] = self.af_step
            else:
                if curr_l < s["ep"]:
                    s["ep"] = curr_l
                    s["af"] = min(s["af"] + self.af_step, self.af_max)

        s["prev_prev_high"] = s["prev_high"]
        s["prev_prev_low"] = s["prev_low"]
        s["prev_high"] = curr_h
        s["prev_low"] = curr_l
        s["sar"] = new_sar

        return {"psar_value": new_sar, "psar_direction": s["direction"]}


plugin = PSARPlugin()
