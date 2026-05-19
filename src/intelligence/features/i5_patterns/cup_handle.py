from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec

_MIN_CUP_BARS = 20
_MAX_CUP_BARS = 60
_HANDLE_BARS = 10
_RIM_TOLERANCE = 0.02  # 2% tolerance for rim symmetry


@dataclass
class CupHandlePlugin:
    """Detect cup-and-handle continuation pattern."""

    name: str = "patt_CupHandle"
    outputs: frozenset[str] = frozenset(
        {
            "cup_handle_pattern",
            "cup_depth_pct",
            "cup_handle_target",
        }
    )
    min_lookback: int = _MIN_CUP_BARS + _HANDLE_BARS
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=80),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {"cup_handle_pattern": 0.0, "cup_depth_pct": None, "cup_handle_target": None}

        close = df["close"].to_numpy(dtype=float)

        # Try cup sizes from max to min (inclusive of _MIN_CUP_BARS)
        for cup_len in range(min(_MAX_CUP_BARS, len(close) - _HANDLE_BARS), _MIN_CUP_BARS - 1, -5):
            handle_end = len(close)
            handle_start = handle_end - _HANDLE_BARS
            cup_end = handle_start
            cup_start = cup_end - cup_len

            if cup_start < 0:
                continue

            cup = close[cup_start:cup_end]
            handle = close[handle_start:handle_end]

            left_rim = float(cup[0])
            right_rim = float(cup[-1])
            cup_bottom = float(np.min(cup))

            # Rim symmetry: right rim within tolerance of left rim
            rim_diff = abs(right_rim - left_rim) / (left_rim if left_rim > 0 else 1.0)
            if rim_diff > _RIM_TOLERANCE:
                continue

            # Cup must have U-shape: bottom significantly below rims
            avg_rim = (left_rim + right_rim) / 2.0
            cup_depth = avg_rim - cup_bottom
            if cup_depth <= 0 or cup_depth / avg_rim < 0.03:  # at least 3% depth
                continue

            # Handle: small pullback < 50% of cup depth, then recovery
            handle_low = float(np.min(handle))
            handle_pullback = avg_rim - handle_low

            if handle_pullback > 0.5 * cup_depth:
                continue

            # Handle should be recovering (close near top of handle range)

            cup_depth_pct = cup_depth / avg_rim
            target = avg_rim + cup_depth  # breakout target = rim + cup depth

            return {
                "cup_handle_pattern": 1.0,
                "cup_depth_pct": round(cup_depth_pct, 4),
                "cup_handle_target": round(target, 4),
            }

        return {
            "cup_handle_pattern": 0.0,
            "cup_depth_pct": None,
            "cup_handle_target": None,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CupHandlePlugin()
