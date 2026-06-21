from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec

_COMPLETION_TOLERANCE = 0.10  # within 10% of D target


@dataclass
class MeasuredMovePlugin:
    """ABCD measured-move pattern using swing high/low features."""

    name: str = "patt_MeasuredMove"
    outputs: frozenset[str] = frozenset(
        {
            "abcd_pattern_active",
            "abcd_direction",
            "abcd_d_target",
            "abcd_completion_pct",
        }
    )
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=60),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        swing_high = features.get("swing_high")
        swing_low = features.get("swing_low")
        swing_high_idx = features.get("swing_high_idx")
        swing_low_idx = features.get("swing_low_idx")
        _close_feat = features.get("close")
        close = float(_close_feat if _close_feat is not None else df["close"].iloc[-1])

        if not all(
            isinstance(v, (int, float))
            for v in [swing_high, swing_low, swing_high_idx, swing_low_idx]
        ):
            return {
                "abcd_pattern_active": 0.0,
                "abcd_direction": 0.0,
                "abcd_d_target": None,
                "abcd_completion_pct": None,
            }

        swing_high = float(swing_high)
        swing_low = float(swing_low)
        hi_idx = int(swing_high_idx)
        lo_idx = int(swing_low_idx)
        ab_range = swing_high - swing_low

        if ab_range <= 0:
            return {
                "abcd_pattern_active": 0.0,
                "abcd_direction": 0.0,
                "abcd_d_target": None,
                "abcd_completion_pct": None,
            }

        # Determine ABCD direction from swing order
        if hi_idx < lo_idx:
            # A=high, B=low, bullish ABCD: price drops to B, recovers to C, target D above A
            # C is current close if between A and B level
            c_point = close
            b_point = swing_low
            bc_retracement = (c_point - b_point) / ab_range if ab_range > 0 else 0
            # Valid BC correction is 0.382–0.786 of AB
            if 0.30 <= bc_retracement <= 0.85:
                d_target = b_point + ab_range  # symmetric: D = B + AB
                direction = 1.0
                denom = d_target - b_point
                completion_pct = (close - b_point) / denom if denom != 0 else 0.0
                completion_pct = max(0.0, min(1.0, completion_pct))
                ab_denom = ab_range if ab_range > 0 else 1.0
                active = 1.0 if abs(close - d_target) / ab_denom < _COMPLETION_TOLERANCE else 0.5
                return {
                    "abcd_pattern_active": active,
                    "abcd_direction": direction,
                    "abcd_d_target": round(d_target, 4),
                    "abcd_completion_pct": round(completion_pct, 4),
                }
        else:
            # A=low, B=high, bearish ABCD
            c_point = close
            b_point = swing_high
            bc_retracement = (b_point - c_point) / ab_range if ab_range > 0 else 0
            if 0.30 <= bc_retracement <= 0.85:
                d_target = swing_low - ab_range  # symmetric: D = A - AB (extends below A)
                direction = -1.0
                denom2 = b_point - d_target
                completion_pct = (b_point - close) / denom2 if denom2 != 0 else 0.0
                completion_pct = max(0.0, min(1.0, completion_pct))
                ab_denom = ab_range if ab_range > 0 else 1.0
                active = 1.0 if abs(close - d_target) / ab_denom < _COMPLETION_TOLERANCE else 0.5
                return {
                    "abcd_pattern_active": active,
                    "abcd_direction": direction,
                    "abcd_d_target": round(d_target, 4),
                    "abcd_completion_pct": round(completion_pct, 4),
                }

        return {
            "abcd_pattern_active": 0.0,
            "abcd_direction": 0.0,
            "abcd_d_target": None,
            "abcd_completion_pct": None,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MeasuredMovePlugin()
