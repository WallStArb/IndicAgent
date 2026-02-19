# src/intelligence/patterns/head_shoulders.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils import find_peaks, find_troughs


@dataclass
class HeadShouldersPlugin:
    name: str = "patt_HeadShoulders"
    outputs: set[str] = frozenset({
        "hs_pattern",
        "hs_neckline",
        "hs_target",
        "hs_confidence",
        "hs_neckline_distance",
    })
    min_lookback: int = 80
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    shoulder_sym_pct: float = 0.05
    head_extend_pct: float = 0.03
    atr_period: int = 14
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        default = {
            "hs_pattern": 0.0, "hs_neckline": 0.0, "hs_target": 0.0,
            "hs_confidence": 0.0, "hs_neckline_distance": 0.0,
        }

        raw_peaks = find_peaks(high, self.neighbor)
        raw_troughs = find_troughs(low, self.neighbor)
        peaks = self._filter_swings(raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True)
        troughs = self._filter_swings(raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False)

        atr = self._compute_atr(high, low, close, self.atr_period)
        current_close = float(close[-1])
        current_bar = len(close) - 1

        # --- Regular H&S (bearish reversal): iterate triplets, pick highest head ---
        # Phantom peaks at base-level bars require triplet-search rather than peaks[-3:].
        hs_best: tuple | None = None
        hs_best_head = 0.0
        for h_pos in range(1, len(peaks) - 1):
            h_idx = peaks[h_pos]
            h_p = float(high[h_idx])
            if h_p <= hs_best_head:
                continue  # can't beat current best
            for rs_pos in range(h_pos + 1, min(len(peaks), h_pos + 6)):
                rs_idx = peaks[rs_pos]
                rs_p = float(high[rs_idx])
                if h_p <= rs_p * (1.0 + self.head_extend_pct):
                    continue
                rt_candidates = [t for t in troughs if h_idx < t < rs_idx]
                if not rt_candidates:
                    continue
                for ls_pos in range(h_pos - 1, max(-1, h_pos - 6), -1):
                    ls_idx = peaks[ls_pos]
                    ls_p = float(high[ls_idx])
                    if h_p <= ls_p * (1.0 + self.head_extend_pct):
                        continue
                    if abs(ls_p - rs_p) / max(ls_p, rs_p) > self.shoulder_sym_pct:
                        continue
                    lt_candidates = [t for t in troughs if ls_idx < t < h_idx]
                    if not lt_candidates:
                        continue
                    lt_idx = min(lt_candidates, key=lambda i: low[i])
                    rt_idx = min(rt_candidates, key=lambda i: low[i])
                    if h_p > hs_best_head:
                        hs_best_head = h_p
                        hs_best = (ls_idx, h_idx, rs_idx, lt_idx, rt_idx,
                                   ls_p, h_p, rs_p,
                                   float(low[lt_idx]), float(low[rt_idx]))

        if hs_best is not None:
            ls_idx, h_idx, rs_idx, lt_idx, rt_idx, ls_p, h_p, rs_p, lt_p, rt_p = hs_best
            neckline_slope = (rt_p - lt_p) / (rt_idx - lt_idx) if rt_idx != lt_idx else 0.0
            neckline_at_bar = lt_p + neckline_slope * (current_bar - lt_idx)
            neckline_at_head = lt_p + neckline_slope * (h_idx - lt_idx)

            pattern = 2.0 if current_close < neckline_at_bar else 1.0
            sym_score = 1.0 - abs(ls_p - rs_p) / max(ls_p, rs_p) / self.shoulder_sym_pct
            confidence = round(max(0.0, min(1.0, sym_score)), 4)
            target = round(neckline_at_head - (h_p - neckline_at_head), 4)
            neckline_distance = round(
                (neckline_at_bar - current_close) / atr if atr > 0 else 0.0, 4
            )
            return {
                "hs_pattern": pattern,
                "hs_neckline": round(neckline_at_bar, 4),
                "hs_target": target,
                "hs_confidence": confidence,
                "hs_neckline_distance": neckline_distance,
            }

        # --- Inverse H&S (bullish reversal): iterate triplets, pick lowest head ---
        ihs_best: tuple | None = None
        ihs_best_head = float("inf")
        for h_pos in range(1, len(troughs) - 1):
            h_idx = troughs[h_pos]
            h_p = float(low[h_idx])
            if h_p >= ihs_best_head:
                continue
            for rs_pos in range(h_pos + 1, min(len(troughs), h_pos + 6)):
                rs_idx = troughs[rs_pos]
                rs_p = float(low[rs_idx])
                if h_p >= rs_p * (1.0 - self.head_extend_pct):
                    continue
                rt_candidates = [p for p in peaks if h_idx < p < rs_idx]
                if not rt_candidates:
                    continue
                for ls_pos in range(h_pos - 1, max(-1, h_pos - 6), -1):
                    ls_idx = troughs[ls_pos]
                    ls_p = float(low[ls_idx])
                    if h_p >= ls_p * (1.0 - self.head_extend_pct):
                        continue
                    if abs(ls_p - rs_p) / max(ls_p, rs_p) > self.shoulder_sym_pct:
                        continue
                    lt_candidates = [p for p in peaks if ls_idx < p < h_idx]
                    if not lt_candidates:
                        continue
                    lt_idx = max(lt_candidates, key=lambda i: high[i])
                    rt_idx = max(rt_candidates, key=lambda i: high[i])
                    if h_p < ihs_best_head:
                        ihs_best_head = h_p
                        ihs_best = (ls_idx, h_idx, rs_idx, lt_idx, rt_idx,
                                    ls_p, h_p, rs_p,
                                    float(high[lt_idx]), float(high[rt_idx]))

        if ihs_best is not None:
            ls_idx, h_idx, rs_idx, lt_idx, rt_idx, ls_p, h_p, rs_p, lt_p, rt_p = ihs_best
            neckline_slope = (rt_p - lt_p) / (rt_idx - lt_idx) if rt_idx != lt_idx else 0.0
            neckline_at_bar = lt_p + neckline_slope * (current_bar - lt_idx)
            neckline_at_head = lt_p + neckline_slope * (h_idx - lt_idx)

            pattern = 4.0 if current_close > neckline_at_bar else 3.0
            sym_score = 1.0 - abs(ls_p - rs_p) / max(ls_p, rs_p) / self.shoulder_sym_pct
            confidence = round(max(0.0, min(1.0, sym_score)), 4)
            target = round(neckline_at_head + (neckline_at_head - h_p), 4)
            neckline_distance = round(
                (current_close - neckline_at_bar) / atr if atr > 0 else 0.0, 4
            )
            return {
                "hs_pattern": pattern,
                "hs_neckline": round(neckline_at_bar, 4),
                "hs_target": target,
                "hs_confidence": confidence,
                "hs_neckline_distance": neckline_distance,
            }

        return default

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

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
    def _compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        n = min(period, len(close) - 1)
        if n < 1:
            return 1.0
        trs = []
        start = max(1, len(close) - n)
        for i in range(start, len(close)):
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 1.0


plugin = HeadShouldersPlugin()
