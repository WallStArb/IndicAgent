from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import is_num


@dataclass
class VolumeEventsPlugin:
    name: str = "evt_VolumeEvents"
    outputs: set[str] = field(
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
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"volume"}))
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

        # Volume spike / drying
        vol_sma = features.get("volume_sma_20")
        vol_std = features.get("volume_std_20")
        if is_num(volume) and is_num(vol_sma) and vol_sma > 0:
            if is_num(vol_std) and vol_std > 0:
                z = (volume - vol_sma) / vol_std
                out["vol_spike"] = 1 if z > self._SPIKE_SIGMA else 0
            else:
                out["vol_spike"] = 1 if volume > vol_sma * (1 + self._SPIKE_SIGMA * 0.5) else 0
            out["vol_drying"] = 1 if volume < vol_sma * self._DRY_RATIO else 0
        else:
            out["vol_spike"] = 0
            out["vol_drying"] = 0

        # BB band touches
        if is_num(bb_upper) and is_num(bb_lower):
            bb_width = bb_upper - bb_lower
            touch_threshold = bb_width * self._BB_TOUCH_PCT
            out["bb_upper_touch"] = 1 if abs(close - bb_upper) <= touch_threshold else 0
            out["bb_lower_touch"] = 1 if abs(close - bb_lower) <= touch_threshold else 0

            # Walking the band: 3+ closes above/below midline
            above_mid = 1 if (is_num(bb_mid) and close > bb_mid) else 0
            below_mid = 1 if (is_num(bb_mid) and close < bb_mid) else 0
            self._state["above_mid_streak"] = (
                (self._state.get("above_mid_streak", 0) + 1) if above_mid else 0
            )
            self._state["below_mid_streak"] = (
                (self._state.get("below_mid_streak", 0) + 1) if below_mid else 0
            )
            out["bb_walking_upper"] = 1 if self._state["above_mid_streak"] >= self._WALK_BARS else 0
            out["bb_walking_lower"] = 1 if self._state["below_mid_streak"] >= self._WALK_BARS else 0
        else:
            out["bb_upper_touch"] = 0
            out["bb_lower_touch"] = 0
            out["bb_walking_upper"] = 0
            out["bb_walking_lower"] = 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolumeEventsPlugin()
