from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import clamp
from src.intelligence.utils.gradient_utils import linear_ramp


@dataclass
class MTFVolatilityPlugin:
    """Multi-timeframe volatility context from cached intel dicts."""

    name: str = "patt_MTFVolatility"
    outputs: frozenset[str] = frozenset(
        {
            "mtf_vol_expansion_15m",
            "mtf_vol_expansion_1h",
            "squeeze_within_expansion",
            "vol_divergence_score",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        intel_15m = frames.get("intel_15m") or {}
        intel_1h = frames.get("intel_1h") or {}

        # vol_expansion: 1.0 = expanding, -1.0 = contracting, 0.0 = neutral
        exp_15m = intel_15m.get("vol_expansion", 0.0) or 0.0
        exp_1h = intel_1h.get("vol_expansion", 0.0) or 0.0

        # Continuous gradient: use upstream values directly instead of binary threshold
        mtf_exp_15m = max(0.0, float(exp_15m))
        mtf_exp_1h = max(0.0, float(exp_1h))

        # squeeze_within_expansion: current TF squeezing while higher TF expanding
        # Compute squeeze independently from I1 BB and Keltner bands — no dependency
        # on bollinger_squeeze plugin output (which runs concurrently in the same wave).
        bb_upper = features.get("bb_20_2_upper") or features.get("bb_upper")
        bb_lower = features.get("bb_20_2_lower") or features.get("bb_lower")
        kc_upper = features.get("keltner_upper")
        kc_lower = features.get("keltner_lower")
        if all(isinstance(v, (int, float)) for v in [bb_upper, bb_lower, kc_upper, kc_lower]):
            bb_width = float(bb_upper) - float(bb_lower)
            kc_width = float(kc_upper) - float(kc_lower)
            is_squeezing = float(bb_upper) < float(kc_upper) and float(bb_lower) > float(kc_lower)
            squeeze_depth = max(0.0, (kc_width - bb_width) / kc_width) if kc_width > 0 else 0.0
        else:
            is_squeezing = False
            squeeze_depth = 0.0
        higher_expansion_mag = max(mtf_exp_15m, mtf_exp_1h)
        if is_squeezing and higher_expansion_mag > 0:
            squeeze_within = linear_ramp(squeeze_depth * higher_expansion_mag, 0, 1.0)
        else:
            squeeze_within = 0.0

        # vol_divergence_score: weighted sum across TFs, clamped to [-1, 1]
        # Weights: 1m (current, from features), 15m, 1h
        cur_exp = float(features.get("vol_expansion") or 0.0)
        divergence = (cur_exp * 1.0 + float(exp_15m) * 0.7 + float(exp_1h) * 0.5) / 2.2
        divergence = clamp(divergence)

        return {
            "mtf_vol_expansion_15m": mtf_exp_15m,
            "mtf_vol_expansion_1h": mtf_exp_1h,
            "squeeze_within_expansion": squeeze_within,
            "vol_divergence_score": round(divergence, 4),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MTFVolatilityPlugin()
