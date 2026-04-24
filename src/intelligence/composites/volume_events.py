from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.common import is_num
from ..utils.gradient_utils import linear_ramp, streak_score, threshold_decay, z_score_to_score


@dataclass
class VolumeEventsPlugin:
    name: str = "evt_VolumeEvents"
    outputs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "vol_spike",
                "vol_drying",
                "bb_upper_touch",
                "bb_lower_touch",
                "bb_walking_upper",
                "bb_walking_lower",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"volume"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    _SPIKE_SIGMA: float = 2.0
    _DRY_RATIO: float = 0.5
    _BB_TOUCH_PCT: float = 0.1  # within 10% of BB width from outer band
    _WALK_BARS: int = 3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        close = features.get("close")
        volume = features.get("volume")
        bb_upper = features.get("bb_20_2_upper")
        bb_lower = features.get("bb_20_2_lower")
        bb_mid = features.get("bb_20_2_mid")
        if bb_mid is None:
            bb_mid = features.get("bb_mid")
        if not is_num(close):
            return {}

        out: dict[str, Any] = {}

        # Volume spike / drying — gradient intensity
        vol_sma = features.get("volume_sma_20")
        vol_std = features.get("volume_std_20")
        if is_num(volume) and is_num(vol_sma) and vol_sma > 0:
            if is_num(vol_std) and vol_std > 0:
                z = (volume - vol_sma) / vol_std
                # Gradient: continuous z-score intensity, saturated at sigma_scale=3.0
                out["vol_spike"] = z_score_to_score(z, sigma_scale=3.0)
            else:
                # Fallback: ratio-based gradient
                ratio = (volume - vol_sma) / vol_sma if vol_sma > 0 else 0.0
                out["vol_spike"] = linear_ramp(ratio, 0.0, self._SPIKE_SIGMA * 0.5)
            # Gradient: drying intensity — higher when volume is much lower than SMA
            dry_threshold = vol_sma * self._DRY_RATIO
            drying_gap = dry_threshold - volume
            out["vol_drying"] = linear_ramp(drying_gap, 0.0, dry_threshold)
        else:
            out["vol_spike"] = 0.0
            out["vol_drying"] = 0.0

        # BB band touches — gradient proximity
        if is_num(bb_upper) and is_num(bb_lower):
            bb_width = bb_upper - bb_lower
            # Gradient: proximity to band decays over 15% of BB width
            proximity_width = bb_width * 0.15
            if proximity_width > 0:
                out["bb_upper_touch"] = threshold_decay(float(close), float(bb_upper), proximity_width)
                out["bb_lower_touch"] = threshold_decay(float(close), float(bb_lower), proximity_width)
            else:
                out["bb_upper_touch"] = 0.0
                out["bb_lower_touch"] = 0.0

            # Walking the band: gradient streak score (saturates at 5 bars)
            above_mid = 1 if (is_num(bb_mid) and close > bb_mid) else 0
            below_mid = 1 if (is_num(bb_mid) and close < bb_mid) else 0
            self._state["above_mid_streak"] = (
                (self._state.get("above_mid_streak", 0) + 1) if above_mid else 0
            )
            self._state["below_mid_streak"] = (
                (self._state.get("below_mid_streak", 0) + 1) if below_mid else 0
            )
            out["bb_walking_upper"] = streak_score(self._state["above_mid_streak"], saturation=5)
            out["bb_walking_lower"] = streak_score(self._state["below_mid_streak"], saturation=5)
        else:
            out["bb_upper_touch"] = 0.0
            out["bb_lower_touch"] = 0.0
            out["bb_walking_upper"] = 0.0
            out["bb_walking_lower"] = 0.0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolumeEventsPlugin()
