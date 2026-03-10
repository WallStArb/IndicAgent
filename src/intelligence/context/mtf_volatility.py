from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import clamp


@dataclass
class MTFVolatilityPlugin:
    """Multi-timeframe volatility context from cached intel dicts."""

    name: str = "ctx_MTFVolatility"
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        intel_15m = frames.get("intel_15m") or {}
        intel_1h = frames.get("intel_1h") or {}

        # vol_expansion: 1.0 = expanding, -1.0 = contracting, 0.0 = neutral
        exp_15m = intel_15m.get("vol_expansion", 0.0) or 0.0
        exp_1h = intel_1h.get("vol_expansion", 0.0) or 0.0

        mtf_exp_15m = 1.0 if float(exp_15m) > 0 else 0.0
        mtf_exp_1h = 1.0 if float(exp_1h) > 0 else 0.0

        # squeeze_within_expansion: current TF squeezing while higher TF expanding
        squeeze_active = features.get("squeeze_active", 0.0) or 0.0
        is_squeezing = isinstance(squeeze_active, (int, float)) and float(squeeze_active) > 0
        higher_expanding = bool(mtf_exp_15m or mtf_exp_1h)
        squeeze_within = 1.0 if (is_squeezing and higher_expanding) else 0.0

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

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MTFVolatilityPlugin()
