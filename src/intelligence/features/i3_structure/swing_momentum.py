"""SwingMomentum I3 plugin — structural momentum from swing amplitude and velocity.

Self-contained: performs its own peak/valley detection using a ±N=3 window.
No dependency on SwingDetector.

Outputs:
    swing_amplitude_ratio      — last swing amplitude vs. mean of last 3 (ATR-normalised)
    swing_amplitude_expanding  — 1 if last 3 amplitudes are monotonically increasing, else 0
    swing_velocity_bars        — bars elapsed for the most recent swing
    swing_velocity_trend       — "accelerating" | "decelerating" | "stable"
    struct_energy              — clamp(amplitude_ratio * speed_factor / 3.0, 0.0, 1.0)
    struct_accel_bias          — +1 uptrend, -1 downtrend, 0 mixed/insufficient
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import clamp, is_num
from src.intelligence.utils.gradient_utils import linear_ramp

# Confirmation window: bar i is a swing high/low if it is the max/min across
# [i-N … i+N] inclusive.
_CONFIRM_N: int = 3
_MAX_EXTREMES: int = 6  # keep the most recent 6 confirmed extremes
_REFERENCE_BARS: int = 20  # typical bars per swing for speed_factor scaling


@dataclass
class SwingMomentumPlugin:
    """I3 structural momentum plugin — swing amplitude and velocity analysis."""

    name: str = "struct_SwingMomentum"
    outputs: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "swing_amplitude_ratio",
                "swing_amplitude_expanding",
                "swing_amplitude_intensity",
                "swing_velocity_bars",
                "swing_velocity_trend",
                "struct_energy",
                "struct_accel_bias",
            }
        )
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset = field(default_factory=lambda: frozenset({"momentum", "structure"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=60),)
    _state: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        n_bars = len(high)

        # --- ATR-14: use pre-computed value from I1 pipeline -----------
        atr = float(frames.get("features", {}).get("atr_14") or 0.0)

        # --- Extreme detection (full-frame rebuild each call) ----------
        extremes = self._detect_extremes(high, low, n_bars)

        # --- Warmup gate ----------------------------------------------
        if len(extremes) < 6:
            return {}

        # --- Use last 6 extremes (3 complete swings) ------------------
        last6 = extremes[-6:]

        # Amplitudes of last 3 swings
        amplitudes = self._compute_amplitudes(last6, atr)

        # Velocity (bars) of last 3 swings
        velocities = self._compute_velocities(last6)

        if not amplitudes or not velocities:
            return {}

        # --- Amplitude outputs ----------------------------------------
        amp_last = amplitudes[-1]
        amp_mean = float(np.mean(amplitudes)) if amplitudes else 1.0
        amplitude_ratio = amp_last / (amp_mean + 1e-9)

        swing_amplitude_expanding = (
            1 if (len(amplitudes) >= 3 and amplitudes[0] < amplitudes[1] < amplitudes[2]) else 0
        )

        swing_amplitude_intensity = (
            linear_ramp(amplitude_ratio, 1.0, 2.0)
            if swing_amplitude_expanding == 1
            else 0.0
        )

        # --- Velocity outputs -----------------------------------------
        swing_velocity_bars = float(velocities[-1])

        if len(velocities) >= 2:
            if velocities[-1] < velocities[-2]:
                velocity_trend = "accelerating"
            elif velocities[-1] > velocities[-2]:
                velocity_trend = "decelerating"
            else:
                velocity_trend = "stable"
        else:
            velocity_trend = "stable"

        # --- struct_energy -------------------------------------------
        speed_factor = clamp(_REFERENCE_BARS / max(swing_velocity_bars, 1.0), 0.1, 3.0)
        struct_energy = clamp(amplitude_ratio * speed_factor / 3.0, 0.0, 1.0)

        # --- struct_accel_bias ----------------------------------------
        struct_accel_bias = self._compute_accel_bias(last6)

        return {
            "swing_amplitude_ratio": float(amplitude_ratio),
            "swing_amplitude_expanding": swing_amplitude_expanding,
            "swing_amplitude_intensity": float(swing_amplitude_intensity),
            "swing_velocity_bars": swing_velocity_bars,
            "swing_velocity_trend": velocity_trend,
            "struct_energy": float(struct_energy),
            "struct_accel_bias": struct_accel_bias,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_extremes(
        high: np.ndarray, low: np.ndarray, n_bars: int
    ) -> list[tuple[float, int, str]]:
        """Return confirmed extremes from the current frame.

        A swing high at bar i is confirmed when:
            high[i] == max(high[i-N : i+N+1])
        A swing low at bar i is confirmed when:
            low[i] == min(low[i-N : i+N+1])

        We only confirm extremes up to bar n_bars - N - 1 (need N bars
        after to confirm).  Returns at most _MAX_EXTREMES recent entries.
        """
        n = _CONFIRM_N
        extremes: list[tuple[float, int, str]] = []

        for i in range(n, n_bars - n):
            lo = i - n
            hi = i + n + 1  # slice end (exclusive)
            window_high = high[lo:hi]
            window_low = low[lo:hi]

            is_peak = high[i] >= np.max(window_high)
            is_trough = low[i] <= np.min(window_low)

            # Prefer peak when bar is both (unusual); track separately.
            if is_peak:
                extremes.append((float(high[i]), i, "high"))
            elif is_trough:
                extremes.append((float(low[i]), i, "low"))

        # Deduplicate consecutive same-type extremes (keep the stronger one).
        extremes = _dedup_extremes(extremes)

        # Keep only the last _MAX_EXTREMES.
        return extremes[-_MAX_EXTREMES:]

    @staticmethod
    def _compute_amplitudes(last6: list[tuple[float, int, str]], atr: float) -> list[float]:
        """Amplitude of each of the 3 swings spanned by the 6 extremes."""
        divisor = atr if (is_num(atr) and atr > 0.0) else 1.0
        amps = []
        for i in range(len(last6) - 1):
            amp = abs(last6[i][0] - last6[i + 1][0]) / divisor
            amps.append(amp)
        return amps

    @staticmethod
    def _compute_velocities(last6: list[tuple[float, int, str]]) -> list[float]:
        """Bars elapsed between consecutive extremes (velocity proxy)."""
        vels = []
        for i in range(len(last6) - 1):
            v = float(abs(last6[i + 1][1] - last6[i][1]))
            vels.append(max(v, 1.0))  # floor at 1 to avoid division by zero
        return vels

    @staticmethod
    def _compute_accel_bias(last6: list[tuple[float, int, str]]) -> int:
        """Return +1 (uptrend), -1 (downtrend), or 0 (mixed/insufficient).

        Strategy: collect last 2 swing highs and last 2 swing lows from
        last6 (in order of bar_index).  Compare the pairs.
        """
        highs = [(p, idx) for p, idx, t in last6 if t == "high"]
        lows = [(p, idx) for p, idx, t in last6 if t == "low"]

        if len(highs) < 2 or len(lows) < 2:
            return 0

        h1, h2 = highs[-2][0], highs[-1][0]
        l1, l2 = lows[-2][0], lows[-1][0]

        higher_highs = h2 > h1
        higher_lows = l2 > l1
        lower_highs = h2 < h1
        lower_lows = l2 < l1

        if higher_highs and higher_lows:
            return 1
        if lower_highs and lower_lows:
            return -1
        return 0


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _dedup_extremes(extremes: list[tuple[float, int, str]]) -> list[tuple[float, int, str]]:
    """Remove consecutive same-type extremes, keeping the dominant one.

    When two consecutive highs appear without an intervening low, keep
    the higher one.  When two consecutive lows appear, keep the lower one.
    This ensures the alternating high/low pattern needed for swing analysis.
    """
    if not extremes:
        return extremes

    result: list[tuple[float, int, str]] = [extremes[0]]
    for current in extremes[1:]:
        prev = result[-1]
        if current[2] == prev[2]:
            # Same type — replace if stronger
            if current[2] == "high" and current[0] >= prev[0]:
                result[-1] = current
            elif current[2] == "low" and current[0] <= prev[0]:
                result[-1] = current
        else:
            result.append(current)

    return result


plugin = SwingMomentumPlugin()
