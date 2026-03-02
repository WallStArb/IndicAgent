from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import crossover_detect, is_num


@dataclass
class MACompositePlugin:
    name: str = "MAComposite"
    outputs: set[str] = field(
        default_factory=lambda: frozenset(
            {
                # 9/21 EMA
                "ema_9_cross_21",
                "ema_9_gt_21",
                "ema_9_21_distance_pct",
                "ema_9_21_slope_agree",
                # 20/50 swing bias (SMA by default)
                "sma_20_cross_50",
                "sma_20_gt_50",
                # Golden/Death cross (SMA50 vs SMA200) — I2 event
                "golden_cross_active",
                "death_cross_active",
                "golden_cross_bars_ago",
                # Dynamic S/R using SMA 50
                "price_above_sma_50",
                "price_touch_sma_50",
                "price_bounce_sma_50",
                # Generic metrics
                "ma_slope_20",
                "ma_slope_50",
                "ma_slope_100",
                "ma_slope_200",
                "ma_slope_delta_20",
                "ma_slope_delta_50",
                "dist_pct_sma_20",
                "dist_pct_sma_50",
                "dist_z_sma_20",
                "dist_z_sma_50",
            }
        )
    )
    min_lookback: int = 200
    supports_incremental: bool = True
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"trend"}))
    inputs: list[InputSpec] = ()  # Consumes upstream features dicts

    atr_key: str = "atr_14"
    bb_mid_key: str = "bb_mid"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        # Expect upstream maps: "ma" (from MovingAveragesPlugin), optional "atr", "bb"
        features = frames.get("features") or {}
        ma = features
        price = features.get("price")  # allow direct pass if provided
        close = features.get("close")
        px = price or close
        out: dict[str, Any] = {}

        # 9/21 EMA
        e9 = ma.get("ema_9")
        e21 = ma.get("ema_21")
        if is_num(e9) and is_num(e21):
            out["ema_9_gt_21"] = 1 if e9 > e21 else 0
            out["ema_9_21_distance_pct"] = float((e9 - e21) / e21) if e21 else 0.0
            # Crossover flag requires prev values if provided via frames
            prev = frames.get("prev_features") or {}
            pe9 = prev.get("ema_9")
            pe21 = prev.get("ema_21")
            if is_num(pe9) and is_num(pe21):
                crossed_up, crossed_down = crossover_detect(pe9, e9, pe21, e21)
                out["ema_9_cross_21"] = 1 if crossed_up else (-1 if crossed_down else 0)
            # Slope agreement if slopes provided
            s9 = features.get("ema_9_slope")
            s21 = features.get("ema_21_slope")
            if is_num(s9) and is_num(s21):
                out["ema_9_21_slope_agree"] = (
                    1 if (s9 >= 0 and s21 >= 0) or (s9 <= 0 and s21 <= 0) else 0
                )

        # 20/50 swing bias (SMA by default)
        s20 = ma.get("sma_20")
        s50 = ma.get("sma_50")
        # Golden/Death cross (SMA50 vs SMA200) — I2 event
        s200 = ma.get("sma_200")
        if is_num(s50) and is_num(s200):
            out["golden_cross_active"] = 1 if s50 > s200 else 0
            out["death_cross_active"] = 1 if s50 < s200 else 0
            # Track bars since last cross using prev_features
            prev = frames.get("prev_features") or {}
            ps50 = prev.get("sma_50")
            ps200 = prev.get("sma_200")
            if is_num(ps50) and is_num(ps200):
                cross_occurred = (ps50 <= ps200 and s50 > s200) or (ps50 >= ps200 and s50 < ps200)
                prev_ago = self._state.get("golden_cross_bars_ago", 999)
                out["golden_cross_bars_ago"] = (
                    0.0 if cross_occurred else float(min(prev_ago + 1, 999))
                )
                self._state["golden_cross_bars_ago"] = out["golden_cross_bars_ago"]
        if is_num(s20) and is_num(s50):
            out["sma_20_gt_50"] = 1 if s20 > s50 else 0
            prev = frames.get("prev_features") or {}
            ps20 = prev.get("sma_20")
            ps50 = prev.get("sma_50")
            if is_num(ps20) and is_num(ps50):
                crossed_up, crossed_down = crossover_detect(ps20, s20, ps50, s50)
                out["sma_20_cross_50"] = 1 if crossed_up else (-1 if crossed_down else 0)

        # Dynamic S/R using SMA 50
        if px is not None and is_num(s200):
            # Both SMAs must be numeric for price_above_sma200 to be valid
            s200 = ma.get("sma_200")
            if isinstance(s200, (int, float)):
                out["price_above_sma200"] = 1 if px > s200 else 0
            else:
                out["price_above_sma200"] = None
            # Touch/bounce within X ATR
            atr = features.get(self.atr_key)
            if is_num(atr) and atr > 0:
                within = abs(px - s50) / atr
                out["price_touch_sma_50"] = 1 if within <= 0.25 else 0
                # Bounce heuristic: touched last bar and moved away this bar
                prev = frames.get("prev_features") or {}
                ppx = prev.get("price")
                ps50v = prev.get("sma_50")
                if is_num(ppx) and is_num(ps50v):
                    prev_within = abs(ppx - ps50v) / atr if atr else 1e9
                    moved_away = abs(px - s50) > abs(ppx - ps50v)
                    out["price_bounce_sma_50"] = 1 if prev_within <= 0.25 and moved_away else 0

        # Price vs SMA200
        if px is not None and is_num(s200):
            out["price_above_sma200"] = 1 if px > s200 else 0
        for p in (20, 50, 100, 200):
            key = f"sma_{p}"
            val = ma.get(key)
            slope = features.get(f"{key}_slope")
            prev_val = (frames.get("prev_features") or {}).get(key)
            if is_num(val) and is_num(prev_val):
                out[f"ma_slope_{p}"] = float(val - prev_val)
                out[f"ma_slope_delta_{p}"] = (
                    float(slope) if is_num(slope) else float(val - prev_val)
                )
                if is_num(px) and val:
                    out[f"dist_pct_{key}"] = float((px - val) / val)
                    atr = features.get(self.atr_key)
                    if is_num(atr) and atr > 0:
                        out[f"dist_z_{key}"] = float((px - val) / atr)

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

plugin = MACompositePlugin()
