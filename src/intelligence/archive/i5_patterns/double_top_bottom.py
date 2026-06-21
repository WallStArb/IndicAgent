# src/intelligence/features/i5_patterns/double_top_bottom.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import find_peaks, find_troughs


@dataclass
class DoubleTBPlugin:
    name: str = "patt_DoubleTB"
    outputs: frozenset[str] = frozenset(
        {
            "dt_db_pattern",
            "dt_db_neckline",
            "dt_db_target",
            "dt_db_confidence",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    peak_tolerance: float = 0.003
    neckline_depth_thr: float = 0.004  # neckline must be ≥0.4% from the peaks
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        if np.any(high <= 0) or np.any(low <= 0):
            return {}

        default = {
            "dt_db_pattern": 0.0,
            "dt_db_neckline": 0.0,
            "dt_db_target": 0.0,
            "dt_db_confidence": 0.0,
        }

        raw_peaks = find_peaks(high, self.neighbor)
        raw_troughs = find_troughs(low, self.neighbor)
        peaks = self._filter_swings(
            raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True
        )
        troughs = self._filter_swings(
            raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False
        )

        current_close = float(close[-1])

        # --- Double Top: iterate all pairs, pick highest-amplitude match ---
        # Phantom peaks arise at base-level bars adjacent to trough regions; requiring
        # neckline_depth_thr and selecting the highest peak_avg eliminates false positives.
        dt_best: tuple | None = None
        dt_best_avg = 0.0
        for p2_pos in range(len(peaks) - 1, 0, -1):
            p2_idx = peaks[p2_pos]
            for p1_pos in range(p2_pos - 1, max(-1, p2_pos - 8), -1):
                p1_idx = peaks[p1_pos]
                p1_p, p2_p = float(high[p1_idx]), float(high[p2_idx])
                peak_avg = (p1_p + p2_p) / 2.0
                if abs(p1_p - p2_p) / peak_avg > self.peak_tolerance:
                    continue
                neck_candidates = [t for t in troughs if p1_idx < t < p2_idx]
                if not neck_candidates:
                    continue
                neck_idx = min(neck_candidates, key=lambda i: low[i])
                neckline = float(low[neck_idx])
                if (min(p1_p, p2_p) - neckline) / min(p1_p, p2_p) < self.neckline_depth_thr:
                    continue
                if peak_avg > dt_best_avg:
                    dt_best_avg = peak_avg
                    dt_best = (p1_idx, p2_idx, neck_idx, neckline, peak_avg, p1_p, p2_p)

        if dt_best is not None:
            p1_idx, p2_idx, neck_idx, neckline, peak_avg, p1_p, p2_p = dt_best
            pattern = 2.0 if current_close < neckline else 1.0
            price_sym = 1.0 - abs(p1_p - p2_p) / peak_avg / self.peak_tolerance
            total_span = p2_idx - p1_idx
            left_span = neck_idx - p1_idx
            time_sym = 1.0 - abs(left_span / total_span - 0.5) * 2.0 if total_span > 0 else 0.5
            confidence = round(max(0.0, min(1.0, (price_sym + time_sym) / 2.0)), 4)
            return {
                "dt_db_pattern": pattern,
                "dt_db_neckline": round(neckline, 4),
                "dt_db_target": round(neckline - (peak_avg - neckline), 4),
                "dt_db_confidence": confidence,
            }

        # --- Double Bottom: iterate all pairs, pick most-depressed match ---
        db_best: tuple | None = None
        db_best_avg = float("inf")
        for t2_pos in range(len(troughs) - 1, 0, -1):
            t2_idx = troughs[t2_pos]
            for t1_pos in range(t2_pos - 1, max(-1, t2_pos - 8), -1):
                t1_idx = troughs[t1_pos]
                t1_p, t2_p = float(low[t1_idx]), float(low[t2_idx])
                trough_avg = (t1_p + t2_p) / 2.0
                if abs(t1_p - t2_p) / trough_avg > self.peak_tolerance:
                    continue
                neck_candidates = [p for p in peaks if t1_idx < p < t2_idx]
                if not neck_candidates:
                    continue
                neck_idx = max(neck_candidates, key=lambda i: high[i])
                neckline = float(high[neck_idx])
                if (neckline - max(t1_p, t2_p)) / neckline < self.neckline_depth_thr:
                    continue
                if trough_avg < db_best_avg:
                    db_best_avg = trough_avg
                    db_best = (t1_idx, t2_idx, neck_idx, neckline, trough_avg, t1_p, t2_p)

        if db_best is not None:
            t1_idx, t2_idx, neck_idx, neckline, trough_avg, t1_p, t2_p = db_best
            pattern = 4.0 if current_close > neckline else 3.0
            price_sym = 1.0 - abs(t1_p - t2_p) / trough_avg / self.peak_tolerance
            total_span = t2_idx - t1_idx
            left_span = neck_idx - t1_idx
            time_sym = 1.0 - abs(left_span / total_span - 0.5) * 2.0 if total_span > 0 else 0.5
            confidence = round(max(0.0, min(1.0, (price_sym + time_sym) / 2.0)), 4)
            return {
                "dt_db_pattern": pattern,
                "dt_db_neckline": round(neckline, 4),
                "dt_db_target": round(neckline + (neckline - trough_avg), 4),
                "dt_db_confidence": confidence,
            }

        return default

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _filter_swings(
        indices: list[int],
        prices: np.ndarray,
        amplitude_thr: float = 0.002,
        min_bars: int = 8,
        keep_max: bool = True,
    ) -> list[int]:
        """Two-stage significance filter: removes noise swings that are too close
        in both price and time. Retains the more extreme swing when merging."""
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


plugin = DoubleTBPlugin()
