from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class DonchianChannelsPlugin:
    """Donchian Channels: N-period highest high / lowest low.

    Breakout indicator used in turtle trading systems.
    Upper = max(high, N), Lower = min(low, N), Mid = average.
    """

    name: str = "DonchianChannels"
    outputs: frozenset[str] = frozenset({"donchian_upper_20", "donchian_mid_20", "donchian_lower_20"})
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"donchian_upper_{self.period}",
                f"donchian_mid_{self.period}",
                f"donchian_lower_{self.period}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}
        high = df["high"]
        low = df["low"]

        upper = float(high.iloc[-self.period :].max())
        lower = float(low.iloc[-self.period :].min())
        mid = (upper + lower) / 2.0

        self._seed_state(frames)
        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
        highs = df["high"].iloc[-self.period :].tolist()
        lows = df["low"].iloc[-self.period :].tolist()
        self._state = {
            "high_window": deque(highs, maxlen=self.period),
            "low_window": deque(lows, maxlen=self.period),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])

        s = self._state
        s["high_window"].append(h)
        s["low_window"].append(lo)

        upper = max(s["high_window"])
        lower = min(s["low_window"])
        mid = (upper + lower) / 2.0

        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }


plugin = DonchianChannelsPlugin()
