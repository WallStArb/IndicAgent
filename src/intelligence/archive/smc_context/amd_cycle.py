"""smc_AMDCycle — ICT Accumulation/Manipulation/Distribution cycle detection.

Three-phase institutional cycle that repeats within each trading day:
  Accumulation:   20:00–00:00 UTC (8pm–midnight ET) — overnight, narrow range
  Manipulation:   00:00–10:00 UTC (midnight–5am ET) — false move beyond overnight range
  Distribution:   10:00–21:00 UTC (5am–4pm ET)      — sustained directional move

The plugin tracks overnight range in rolling state and detects when
manipulation-phase price spikes breach and then reverse from that range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import utc_datetime_from_df

# UTC hour boundaries
_ACCUM_START = 20
_ACCUM_END = 24  # wraps at midnight (0)
_MANIP_END = 10
_DIST_END = 21


def _utc_hour(df: Any) -> int | None:
    """Extract UTC hour from the last bar's timestamp column, or return None."""
    dt = utc_datetime_from_df(df)
    return dt.hour if dt is not None else None


@dataclass
class AMDCyclePlugin:
    """Detect current AMD cycle phase and manipulation events."""

    name: str = "smc_AMDCycle"
    outputs: frozenset[str] = frozenset(
        {
            "amd_phase",
            "amd_manipulation_detected",
            "amd_distribution_direction",
            "manip_strength",
        }
    )
    min_lookback: int = 2
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money", "session"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=30),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = float(df["close"].iloc[-1])
        high = float(df["high"].iloc[-1])
        low = float(df["low"].iloc[-1])

        hour = _utc_hour(df)
        if hour is None:
            # No timestamp — return neutral
            return {
                "amd_phase": "unknown",
                "amd_manipulation_detected": 0.0,
                "amd_distribution_direction": 0.0,
                "manip_strength": 0.0,
            }

        # Determine phase
        if hour >= _ACCUM_START:
            phase = "accumulation"
        elif hour < _MANIP_END:
            phase = "manipulation"
        elif hour < _DIST_END:
            phase = "distribution"
        else:
            phase = "accumulation"

        # Update overnight range during accumulation; reset cycle flags each session
        key_sym = "overnight"
        if phase == "accumulation":
            prev = self._state.get(key_sym, {})
            self._state[key_sym] = {
                "high": max(prev.get("high", high), high),
                "low": min(prev.get("low", low), low),
            }
            # Reset per-cycle flags so next day's distribution/manipulation fire fresh
            self._state["dist_reset_done"] = False
            self._state["manipulation_done"] = False
        elif phase == "distribution":
            # Reset overnight state when we enter distribution
            if self._state.get("dist_reset_done") is not True:
                self._state["dist_reset_done"] = True
                self._state["dist_direction"] = 0.0
                manip = self._state.get("manipulation_done", False)
                if manip:
                    # Direction: based on whether manipulation was a sweep high or sweep low
                    self._state["dist_direction"] = self._state.get("manip_direction", 0.0)

        # Manipulation detection: breach overnight range then reverse
        manip_detected = 0.0
        manip_strength = 0.0
        overnight = self._state.get(key_sym, {})
        on_high = overnight.get("high")
        on_low = overnight.get("low")
        on_range = (on_high - on_low) if (on_high is not None and on_low is not None) else 0.0

        if phase == "manipulation" and on_high is not None and on_low is not None:
            # Sweep high then reverse down
            if high > on_high and close < on_high:
                manip_detected = 1.0
                manip_strength = (high - on_high) / on_range if on_range > 0 else 0.0
                self._state["manipulation_done"] = True
                self._state["manip_direction"] = -1.0  # bearish distribution expected
            # Sweep low then reverse up
            elif low < on_low and close > on_low:
                manip_detected = 1.0
                manip_strength = (on_low - low) / on_range if on_range > 0 else 0.0
                self._state["manipulation_done"] = True
                self._state["manip_direction"] = 1.0  # bullish distribution expected

        dist_direction = self._state.get("dist_direction", 0.0) if phase == "distribution" else 0.0

        return {
            "amd_phase": phase,
            "amd_manipulation_detected": manip_detected,
            "amd_distribution_direction": dist_direction,
            "manip_strength": round(manip_strength, 4),
        }


plugin = AMDCyclePlugin()
