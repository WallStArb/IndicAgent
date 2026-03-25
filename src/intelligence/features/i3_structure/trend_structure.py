from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import find_peaks, find_troughs


@dataclass
class TrendStructurePlugin:
    """Classify trend regime from swing sequence and structural integrity."""

    name: str = "struct_TrendStructure"
    outputs: frozenset[str] = frozenset(
        {
            "trend_direction",
            "trend_strength",
            "trend_leg_count",
            "structure_integrity",
            "price_position",
            "trend_duration_bars",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        n_bars = len(df)

        swing_highs = find_peaks(high, self.neighbor)
        swing_lows = find_troughs(low, self.neighbor)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {
                "trend_direction": 0.0,
                "trend_strength": 0.0,
                "trend_leg_count": 0.0,
                "structure_integrity": 0.0,
                "price_position": 0.5,
                "trend_duration_bars": 0.0,
            }

        # Score consecutive swing pairs
        bullish_legs = 0
        bearish_legs = 0

        for i in range(1, len(swing_highs)):
            if high[swing_highs[i]] > high[swing_highs[i - 1]]:
                bullish_legs += 1
            elif high[swing_highs[i]] < high[swing_highs[i - 1]]:
                bearish_legs += 1

        for i in range(1, len(swing_lows)):
            if low[swing_lows[i]] > low[swing_lows[i - 1]]:
                bullish_legs += 1
            elif low[swing_lows[i]] < low[swing_lows[i - 1]]:
                bearish_legs += 1

        total_legs = bullish_legs + bearish_legs
        if total_legs == 0:
            direction = 0.0
            leg_count = 0.0
        elif bullish_legs > bearish_legs:
            direction = 1.0
            leg_count = float(bullish_legs)
        elif bearish_legs > bullish_legs:
            direction = -1.0
            leg_count = float(bearish_legs)
        else:
            direction = 0.0
            leg_count = 0.0

        # Trend strength: ratio of dominant legs to total
        strength = max(bullish_legs, bearish_legs) / total_legs if total_legs > 0 else 0.0

        # ATR normalisation if available
        features = frames.get("features")
        if isinstance(features, dict) and "atr_14" in features:
            atr = features["atr_14"]
            if atr > 0:
                price_range = float(np.max(high[-20:]) - np.min(low[-20:]))
                strength = min(1.0, strength * (price_range / atr) / 5.0)

        # Structure integrity: how clean are the swings (no overlapping)?
        overlap_count = 0
        all_swings = sorted(
            [(idx, "H", float(high[idx])) for idx in swing_highs]
            + [(idx, "L", float(low[idx])) for idx in swing_lows],
            key=lambda x: x[0],
        )

        for i in range(1, len(all_swings)):
            prev_type, prev_val = all_swings[i - 1][1], all_swings[i - 1][2]
            curr_type, curr_val = all_swings[i][1], all_swings[i][2]
            if prev_type == "H" and curr_type == "L" and curr_val > prev_val:
                overlap_count += 1
            elif prev_type == "L" and curr_type == "H" and curr_val < prev_val:
                overlap_count += 1

        max_overlaps = max(len(all_swings) - 1, 1)
        integrity = 1.0 - overlap_count / max_overlaps

        # Price position in recent swing range
        recent_high = float(np.max(high[swing_highs[-1] :]))
        recent_low = float(np.min(low[swing_lows[-1] :]))
        recent_high = max(recent_high, float(high[swing_highs[-1]]))
        recent_low = min(recent_low, float(low[swing_lows[-1]]))
        swing_range = recent_high - recent_low
        if swing_range > 0:
            position = (float(close[-1]) - recent_low) / swing_range
            position = max(0.0, min(1.0, position))
        else:
            position = 0.5

        # Trend duration: bars since the start of the current directional streak
        trend_duration = self._compute_trend_duration(
            direction,
            swing_highs,
            swing_lows,
            high,
            low,
            n_bars,
        )

        return {
            "trend_direction": direction,
            "trend_strength": round(strength, 4),
            "trend_leg_count": leg_count,
            "structure_integrity": round(integrity, 4),
            "price_position": round(position, 4),
            "trend_duration_bars": trend_duration,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _compute_trend_duration(
        direction: float,
        swing_highs: list[int],
        swing_lows: list[int],
        high: np.ndarray,
        low: np.ndarray,
        n_bars: int,
    ) -> float:
        """Bars since the start of the current directional swing streak."""
        if direction == 1.0 and len(swing_highs) >= 2:
            # Walk backward through highs to find where HH streak begins
            streak_start = swing_highs[-1]
            for i in range(len(swing_highs) - 1, 0, -1):
                if high[swing_highs[i]] > high[swing_highs[i - 1]]:
                    streak_start = swing_highs[i - 1]
                else:
                    break
            return float(n_bars - 1 - streak_start)
        elif direction == -1.0 and len(swing_lows) >= 2:
            streak_start = swing_lows[-1]
            for i in range(len(swing_lows) - 1, 0, -1):
                if low[swing_lows[i]] < low[swing_lows[i - 1]]:
                    streak_start = swing_lows[i - 1]
                else:
                    break
            return float(n_bars - 1 - streak_start)
        return 0.0


plugin = TrendStructurePlugin()
