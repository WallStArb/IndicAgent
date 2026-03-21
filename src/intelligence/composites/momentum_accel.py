# src/intelligence/composites/momentum_accel.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.common import is_num


@dataclass
class MomentumAccelPlugin:
    name: str = "evt_MomentumAcceleration"
    outputs: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "rsi_accel",
                "macd_accel",
                "roc_accel",
                "inflection_flag",
                "rsi_curvature",
                "macd_hist_slope",
                "price_accel",
                "hma_slope",
                "hma_accel",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        prev = frames.get("prev_features") or {}
        df = frames.get("main")

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
            # rsi_curvature uses OLD prev_rsi_accel (before state write)
            rsi_curvature = (rsi_accel - prev_rsi_accel) if is_num(prev_rsi_accel) else 0.0
            if is_num(prev_rsi_accel) and prev_rsi_accel * rsi_accel < 0:
                inflection = 1
            self._state["prev_rsi_accel"] = rsi_accel
            out["rsi_accel"] = rsi_accel
            out["rsi_curvature"] = rsi_curvature
        else:
            out["rsi_accel"] = 0.0
            out["rsi_curvature"] = 0.0

        # MACD signal-line acceleration
        if is_num(macd) and is_num(prev_macd):
            macd_accel = macd - prev_macd
            prev_macd_accel = self._state.get("prev_macd_accel")
            if is_num(prev_macd_accel) and prev_macd_accel * macd_accel < 0:
                inflection = 1
            self._state["prev_macd_accel"] = macd_accel
            out["macd_accel"] = macd_accel
        else:
            out["macd_accel"] = 0.0

        # MACD histogram slope (state-based, not prev_features)
        macd_hist = features.get("macd_histogram_12_26_9")
        if is_num(macd_hist):
            prev_macd_hist = self._state.get("prev_macd_hist")
            macd_hist_slope = (macd_hist - prev_macd_hist) if is_num(prev_macd_hist) else 0.0
            self._state["prev_macd_hist"] = macd_hist
            out["macd_hist_slope"] = macd_hist_slope
        else:
            out["macd_hist_slope"] = 0.0

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

        # Price acceleration: ((close[-1]-close[-2]) - (close[-3]-close[-4])) / atr
        # Requires at least 4 bars and a valid ATR.
        atr = features.get("atr_14")
        if df is not None and len(df) >= 4 and is_num(atr) and atr > 0:
            c = df["close"].to_numpy()
            velocity_now = float(c[-1]) - float(c[-2])
            velocity_prev = float(c[-3]) - float(c[-4])
            out["price_accel"] = (velocity_now - velocity_prev) / atr
        else:
            out["price_accel"] = 0.0

        # HMA slope and acceleration (state-based)
        hma_20 = features.get("hma_20")
        if is_num(hma_20):
            prev_hma_20 = self._state.get("prev_hma_20")
            hma_slope = (hma_20 - prev_hma_20) if is_num(prev_hma_20) else 0.0

            prev_hma_slope = self._state.get("prev_hma_slope")
            hma_accel = (hma_slope - prev_hma_slope) if is_num(prev_hma_slope) else 0.0

            self._state["prev_hma_20"] = hma_20
            self._state["prev_hma_slope"] = hma_slope

            out["hma_slope"] = hma_slope
            out["hma_accel"] = hma_accel
        else:
            out["hma_slope"] = 0.0
            out["hma_accel"] = 0.0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumAccelPlugin()
