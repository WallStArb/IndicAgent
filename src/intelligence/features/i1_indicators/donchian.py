"""Donchian Channels plugin -- migrated to IncrementalMixin.

State ownership: IncrementalMixin handles _state lifecycle.
Implements:
- _compute_full_core(frames) -> dict: full Donchian computation
- _compute_next_core(frames, state) -> dict: single-bar incremental update
- _seed_state(frames) -> dict: extract deque state from full computation
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin


@dataclass
class DonchianChannelsPlugin(IncrementalMixin):
    """Donchian Channels: N-period highest high / lowest low.

    Breakout indicator used in turtle trading systems.
    Upper = max(high, N), Lower = min(low, N), Mid = average.
    """

    name: str = "DonchianChannels"
    outputs: frozenset[str] = frozenset(
        {"donchian_upper_20", "donchian_mid_20", "donchian_lower_20"}
    )
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    period: int = 20

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"donchian_upper_{self.period}",
                f"donchian_mid_{self.period}",
                f"donchian_lower_{self.period}",
            }
        )

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """Full Donchian computation. Returns outputs only (no _state)."""
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}
        high = df["high"]
        low = df["low"]

        upper = float(high.iloc[-self.period :].max())
        lower = float(low.iloc[-self.period :].min())
        mid = (upper + lower) / 2.0

        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        """Extract deque state from full computation for incremental seeding."""
        df = frames.get("main")
        if df is None:
            return {}
        highs = df["high"].iloc[-self.period :].tolist()
        lows = df["low"].iloc[-self.period :].tolist()
        return {
            "high_window": deque(highs, maxlen=self.period),
            "low_window": deque(lows, maxlen=self.period),
        }

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        """Single-bar incremental Donchian update. Mutates state in place."""
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])

        state["high_window"].append(h)
        state["low_window"].append(lo)

        upper = max(state["high_window"])
        lower = min(state["low_window"])
        mid = (upper + lower) / 2.0

        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }


plugin = DonchianChannelsPlugin()
