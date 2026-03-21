from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.common import crossover_detect, is_num, track_bars_ago


@dataclass
class MACDEventsPlugin:
    name: str = "evt_MACDEvents"
    outputs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "macd_cross_bullish",
                "macd_cross_bearish",
                "macd_cross_bars_ago",
                "macd_hist_positive",
                "macd_hist_turning_up",
                "macd_negative_support_test",
                "macd_hist_accel",  # rate of change of MACD histogram
                "macd_hist_contracting",  # 1 when abs(hist) < abs(prev_hist)
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # Constants
    _SUPPORT_ATR_THRESHOLD: float = 1.0

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        macd = features.get("macd_12_26_9")
        signal = features.get("macd_signal_12_26_9")
        hist = features.get("macd_histogram_12_26_9")
        if not all(is_num(v) for v in [macd, signal, hist]):
            return {}

        out: dict[str, Any] = {}
        prev = frames.get("prev_features") or {}
        prev_macd = prev.get("macd_12_26_9")
        prev_signal = prev.get("macd_signal_12_26_9")
        prev_hist = prev.get("macd_histogram_12_26_9")

        # Crossover detection
        cross_bullish, cross_bearish = crossover_detect(prev_macd, macd, prev_signal, signal)
        out["macd_cross_bullish"] = cross_bullish
        out["macd_cross_bearish"] = cross_bearish

        # Track bars since last cross
        out["macd_cross_bars_ago"] = track_bars_ago(
            self._state, "cross_bars_ago", cross_bullish or cross_bearish
        )

        # Histogram state
        out["macd_hist_positive"] = 1 if hist > 0 else 0
        turning_up = 0
        if is_num(prev_hist):
            turning_up = 1 if prev_hist < 0 and hist > prev_hist else 0
        out["macd_hist_turning_up"] = turning_up

        # Histogram acceleration: rate of change of histogram (early exhaustion warning)
        out["macd_hist_accel"] = float(hist - prev_hist) if is_num(prev_hist) else 0.0
        # Histogram contracting: 1 when magnitude is shrinking (approaching zero)
        out["macd_hist_contracting"] = (
            1 if (is_num(prev_hist) and abs(hist) < abs(prev_hist)) else 0
        )

        # Negative support test: MACD hist negative + price near support
        nearest_support = features.get("nearest_support")
        close = features.get("close")
        atr = features.get("atr_14")
        neg_support = 0
        if hist < 0 and is_num(nearest_support) and is_num(close) and is_num(atr) and atr > 0:
            dist = abs(close - nearest_support) / atr
            neg_support = 1 if dist < self._SUPPORT_ATR_THRESHOLD else 0
        out["macd_negative_support_test"] = neg_support

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MACDEventsPlugin()
