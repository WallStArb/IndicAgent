# src/intelligence/features/i5_patterns/triangle_wedge.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import find_peaks, find_troughs


@dataclass
class TriangleWedgePlugin:
    name: str = "patt_TriangleWedge"
    outputs: frozenset[str] = frozenset(
        {
            "tri_pattern",
            "tri_upper_slope",
            "tri_lower_slope",
            "tri_apex_bars",
            "tri_breakout_bias",
            "tri_confidence",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    slope_tolerance: float = 0.0001
    min_swing_points: int = 2
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        default = {
            "tri_pattern": 0.0,
            "tri_upper_slope": 0.0,
            "tri_lower_slope": 0.0,
            "tri_apex_bars": 0.0,
            "tri_breakout_bias": 0.0,
            "tri_confidence": 0.0,
        }

        # Upper trendline: peaks of high
        raw_peaks = find_peaks(high, self.neighbor)
        peaks = self._filter_swings(
            raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True
        )

        # Lower trendline: try find_troughs(low) first; if the lower trendline's troughs are
        # above the surrounding base (e.g., rising-wedge scenarios where low injections create
        # bumps), find_troughs returns phantom flat troughs at base level.  In that case, use
        # find_peaks(low) instead — the "peaks of low" are local-maximum support touches that
        # correctly capture the rising lower channel.
        raw_troughs = find_troughs(low, self.neighbor)
        troughs_min = self._filter_swings(
            raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False
        )

        raw_low_peaks = find_peaks(low, self.neighbor)
        troughs_max = self._filter_swings(
            raw_low_peaks, low, self.amplitude_thr, self.min_swing_bars, keep_max=True
        )

        troughs = self._pick_lower_trendline(troughs_min, troughs_max, low)

        if len(peaks) < self.min_swing_points or len(troughs) < self.min_swing_points:
            return default

        # Linear regression on upper trendline (peaks) and lower trendline (troughs)
        px = np.array(peaks, dtype=float)
        py = np.array([float(high[i]) for i in peaks], dtype=float)
        slope_h, intercept_h, r2_upper = self._linreg(px, py)

        tx = np.array(troughs, dtype=float)
        ty = np.array([float(low[i]) for i in troughs], dtype=float)
        slope_l, intercept_l, r2_lower = self._linreg(tx, ty)

        tol = self.slope_tolerance
        pattern = 0.0
        bias = 0.0

        if abs(slope_h) <= tol and slope_l > tol:
            pattern, bias = 1.0, 1.0  # ascending triangle → bullish
        elif slope_h < -tol and abs(slope_l) <= tol:
            pattern, bias = 2.0, -1.0  # descending triangle → bearish
        elif slope_h < -tol and slope_l > tol:
            pattern, bias = 3.0, 0.0  # symmetrical triangle → continuation
        elif slope_h > tol and slope_l > tol and slope_l > slope_h:
            pattern, bias = 4.0, -1.0  # rising wedge → bearish
        elif slope_h < -tol and slope_l < -tol and slope_h < slope_l:
            pattern, bias = 5.0, 1.0  # falling wedge → bullish

        if pattern == 0.0:
            return default

        # Apex: bar where upper and lower trendlines converge
        apex_bars = 0.0
        denom = slope_h - slope_l
        if abs(denom) > 1e-10:
            apex_bar = (intercept_l - intercept_h) / denom
            bars_to_apex = apex_bar - float(len(high) - 1)
            apex_bars = round(max(0.0, bars_to_apex), 1)

        # Convergence ratio: how much the channel has tightened
        first_bar = float(min(peaks[0], troughs[0]))
        last_bar = float(len(high) - 1)
        initial_width = (slope_h * first_bar + intercept_h) - (slope_l * first_bar + intercept_l)
        current_width = (slope_h * last_bar + intercept_h) - (slope_l * last_bar + intercept_l)

        convergence = 0.0
        if initial_width > 1e-6:
            convergence = max(0.0, min(1.0, 1.0 - current_width / initial_width))

        r2_combined = (r2_upper * r2_lower) ** 0.5
        confidence = round(convergence * r2_combined, 4)

        return {
            "tri_pattern": pattern,
            "tri_upper_slope": round(slope_h, 6),
            "tri_lower_slope": round(slope_l, 6),
            "tri_apex_bars": apex_bars,
            "tri_breakout_bias": bias,
            "tri_confidence": confidence,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _pick_lower_trendline(
        troughs_min: list[int],
        troughs_max: list[int],
        low: np.ndarray,
    ) -> list[int]:
        """Choose the more informative lower trendline series.

        When trough injections place prices above the local base (e.g. rising-wedge data),
        find_troughs returns flat phantom troughs at base level while find_peaks(low)
        correctly captures the rising support touches.  Pick whichever has higher absolute
        slope — this selects the series that actually carries trend information.
        """

        def _slope(indices: list[int], arr: np.ndarray) -> float:
            if len(indices) < 2:
                return 0.0
            x = np.array(indices, dtype=float)
            y = np.array([arr[i] for i in indices], dtype=float)
            x_mean = x.mean()
            ss_xx = float(((x - x_mean) ** 2).sum())
            if ss_xx < 1e-10:
                return 0.0
            return float(((x - x_mean) * (y - y.mean())).sum()) / ss_xx

        s_min = abs(_slope(troughs_min, low))
        s_max = abs(_slope(troughs_max, low))

        if len(troughs_max) >= 2 and s_max > s_min:
            return troughs_max
        if len(troughs_min) >= 2:
            return troughs_min
        return troughs_max

    @staticmethod
    def _filter_swings(
        indices: list[int],
        prices: np.ndarray,
        amplitude_thr: float = 0.002,
        min_bars: int = 8,
        keep_max: bool = True,
    ) -> list[int]:
        if not indices:
            return []
        filtered = [indices[0]]
        for idx in indices[1:]:
            prev_idx = filtered[-1]
            bar_gap = idx - prev_idx
            ref = prices[prev_idx]
            price_diff = abs(prices[idx] - ref) / ref if ref != 0 else 1.0
            if bar_gap >= min_bars or price_diff >= amplitude_thr:
                filtered.append(idx)
            else:
                if keep_max and prices[idx] > prices[prev_idx]:
                    filtered[-1] = idx
                elif not keep_max and prices[idx] < prices[prev_idx]:
                    filtered[-1] = idx
        return filtered

    @staticmethod
    def _linreg(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
        """Returns (slope, intercept, r2). Requires len >= 2."""
        n = len(x)
        if n < 2:
            return 0.0, float(y[0]) if n == 1 else 0.0, 0.0
        x_mean, y_mean = x.mean(), y.mean()
        ss_xy = float(((x - x_mean) * (y - y_mean)).sum())
        ss_xx = float(((x - x_mean) ** 2).sum())
        if ss_xx < 1e-10:
            return 0.0, y_mean, 1.0
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        y_pred = slope * x + intercept
        ss_res = float(((y - y_pred) ** 2).sum())
        ss_tot = float(((y - y_mean) ** 2).sum())
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 1.0
        return slope, intercept, max(0.0, min(1.0, r2))


plugin = TriangleWedgePlugin()
