from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec

_LOOKBACK = 40
_CONSOL_BARS = 10
_MIN_IMPULSE_BARS = 5


@dataclass
class FlagPennantPlugin:
    """Detect bull/bear flag and pennant continuation patterns."""

    name: str = "patt_FlagPennant"
    outputs: frozenset[str] = frozenset(
        {
            "flag_pattern",
            "pennant_pattern",
            "flag_breakout_target",
            "consolidation_compression_ratio",
        }
    )
    min_lookback: int = _LOOKBACK
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=60),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        bar_ranges = high - low
        avg_range = float(np.mean(bar_ranges))
        if avg_range <= 0:
            return {}

        # Consolidation = last CONSOL_BARS bars
        consol = close[-_CONSOL_BARS:]
        consol_ranges = bar_ranges[-_CONSOL_BARS:]
        avg_consol_range = float(np.mean(consol_ranges))

        # Impulse = bars before consolidation
        impulse_window = close[-_LOOKBACK:-_CONSOL_BARS]
        impulse_ranges = bar_ranges[-_LOOKBACK:-_CONSOL_BARS]

        if len(impulse_window) < _MIN_IMPULSE_BARS:
            return {}

        # Detect impulse: consecutive above-avg range bars with net directional move
        impulse_move = float(impulse_window[-1] - impulse_window[0])
        impulse_magnitude = abs(impulse_move)
        impulse_direction = 1.0 if impulse_move > 0 else (-1.0 if impulse_move < 0 else 0.0)

        # Impulse must be strong: > 1.5× average range per bar
        avg_impulse_range = float(np.mean(impulse_ranges))
        is_impulse = avg_impulse_range > 1.2 * avg_range and impulse_magnitude > 3 * avg_range

        if not is_impulse:
            return {
                "flag_pattern": 0.0,
                "pennant_pattern": 0.0,
                "flag_breakout_target": None,
                "consolidation_compression_ratio": (
                    avg_consol_range / avg_impulse_range if avg_impulse_range > 0 else None
                ),
            }

        # Consolidation must be tight compared to impulse
        is_consolidation = avg_consol_range < 0.5 * avg_impulse_range

        if not is_consolidation:
            return {
                "flag_pattern": 0.0,
                "pennant_pattern": 0.0,
                "flag_breakout_target": None,
                "consolidation_compression_ratio": avg_consol_range / avg_impulse_range,
            }

        compression_ratio = avg_consol_range / avg_impulse_range

        # Fit trendlines to consolidation highs and lows
        x = np.arange(_CONSOL_BARS, dtype=float)
        consol_highs = high[-_CONSOL_BARS:]
        consol_lows = low[-_CONSOL_BARS:]

        try:
            upper_slope = float(np.polyfit(x, consol_highs, 1)[0])
            lower_slope = float(np.polyfit(x, consol_lows, 1)[0])
        except (np.linalg.LinAlgError, ValueError):
            return {
                "flag_pattern": 0.0,
                "pennant_pattern": 0.0,
                "flag_breakout_target": None,
                "consolidation_compression_ratio": round(compression_ratio, 4),
            }
        if np.isnan(upper_slope) or np.isnan(lower_slope):
            return {
                "flag_pattern": 0.0,
                "pennant_pattern": 0.0,
                "flag_breakout_target": None,
                "consolidation_compression_ratio": round(compression_ratio, 4),
            }

        # Flag: slopes same sign (both falling or both rising after impulse)
        flag_pattern = 0.0
        if upper_slope * lower_slope > 0:
            flag_pattern = impulse_direction

        # Pennant: slopes converge (opposite signs)
        pennant_pattern = 0.0
        if upper_slope * lower_slope < 0:
            pennant_pattern = impulse_direction

        # Breakout target = consolidation start + impulse magnitude
        consol_start_price = float(consol[0])
        flag_breakout_target = (
            consol_start_price + impulse_direction * impulse_magnitude
            if (flag_pattern != 0.0 or pennant_pattern != 0.0)
            else None
        )

        return {
            "flag_pattern": flag_pattern,
            "pennant_pattern": pennant_pattern,
            "flag_breakout_target": flag_breakout_target,
            "consolidation_compression_ratio": round(compression_ratio, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FlagPennantPlugin()
