# src/intelligence/composites/momentum_accel.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import is_num


@dataclass
class MomentumAccelPlugin:
    name: str = "evt_MomentumAcceleration"
    outputs: frozenset = field(
        default_factory=lambda: frozenset({
            "rsi_accel",
            "macd_accel",
            "roc_accel",
            "inflection_flag",
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(
        default_factory=lambda: frozenset({"momentum"})
    )
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        prev = frames.get("prev_features") or {}

        rsi = features.get("rsi_14")
        macd = features.get("macd_12_26_9")
        roc = features.get("roc_14")

        prev_rsi = prev.get("rsi_14")
        prev_macd = prev.get("macd_12_26_9")
        prev_roc = prev.get("roc_14")

        out: dict[str, Any] = {}
        inflection = 0

        # RSI acceleration
        if is_num(rsi) and is_num(prev_rsi):
            rsi_accel = rsi - prev_rsi
            prev_rsi_accel = self._state.get("prev_rsi_accel")
            if is_num(prev_rsi_accel) and prev_rsi_accel * rsi_accel < 0:
                inflection = 1
            self._state["prev_rsi_accel"] = rsi_accel
            out["rsi_accel"] = rsi_accel
        else:
            out["rsi_accel"] = 0.0

        # MACD acceleration
        if is_num(macd) and is_num(prev_macd):
            macd_accel = macd - prev_macd
            prev_macd_accel = self._state.get("prev_macd_accel")
            if is_num(prev_macd_accel) and prev_macd_accel * macd_accel < 0:
                inflection = 1
            self._state["prev_macd_accel"] = macd_accel
            out["macd_accel"] = macd_accel
        else:
            out["macd_accel"] = 0.0

        # ROC acceleration
        if is_num(roc) and is_num(prev_roc):
            roc_accel = roc - prev_roc
            prev_roc_accel = self._state.get("prev_roc_accel")
            if is_num(prev_roc_accel) and prev_roc_accel * roc_accel < 0:
                inflection = 1
            self._state["prev_roc_accel"] = roc_accel
            out["roc_accel"] = roc_accel
        else:
            out["roc_accel"] = 0.0

        out["inflection_flag"] = inflection
        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumAccelPlugin()
