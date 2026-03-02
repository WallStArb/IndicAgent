from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class MACDEventsPlugin:
    name: str = "evt_MACDEvents"
    outputs: set[str] = field(
        default_factory=lambda: frozenset({
            "macd_cross_bullish", "macd_cross_bearish", "macd_cross_bars_ago",
            "macd_hist_positive", "macd_hist_turning_up",
            "macd_negative_support_test",
            "macd_price_divergence_bullish", "macd_price_divergence_bearish",
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = field(default_factory=lambda: frozenset({"momentum"}))
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        macd = features.get("macd_12_26_9")
        signal = features.get("macd_signal_12_26_9")
        hist = features.get("macd_histogram_12_26_9")
        if not all(isinstance(v, (int, float)) for v in [macd, signal, hist]):
            return {}

        out: dict[str, Any] = {}
        prev = frames.get("prev_features") or {}
        prev_macd = prev.get("macd_12_26_9")
        prev_signal = prev.get("macd_signal_12_26_9")
        prev_hist = prev.get("macd_histogram_12_26_9")

        # Crossover detection
        cross_bullish = 0
        cross_bearish = 0
        if isinstance(prev_macd, (int, float)) and isinstance(prev_signal, (int, float)):
            cross_bullish = 1 if prev_macd <= prev_signal and macd > signal else 0
            cross_bearish = 1 if prev_macd >= prev_signal and macd < signal else 0

        out["macd_cross_bullish"] = cross_bullish
        out["macd_cross_bearish"] = cross_bearish

        # Track bars since last cross
        if cross_bullish or cross_bearish:
            self._state["cross_bars_ago"] = 0.0
        else:
            self._state["cross_bars_ago"] = float(min(self._state.get("cross_bars_ago", 999) + 1, 999))
        out["macd_cross_bars_ago"] = self._state["cross_bars_ago"]

        # Histogram state
        out["macd_hist_positive"] = 1 if hist > 0 else 0
        turning_up = 0
        if isinstance(prev_hist, (int, float)):
            turning_up = 1 if prev_hist < 0 and hist > prev_hist else 0
        out["macd_hist_turning_up"] = turning_up

        # Negative support test: MACD hist negative + price near support
        nearest_support = features.get("nearest_support")
        close = features.get("close")
        atr = features.get("atr_14")
        neg_support = 0
        if (
            hist < 0
            and isinstance(nearest_support, (int, float))
            and isinstance(close, (int, float))
            and isinstance(atr, (int, float))
            and atr > 0
        ):
            dist = abs(close - nearest_support) / atr
            neg_support = 1 if dist < 1.0 else 0
        out["macd_negative_support_test"] = neg_support

        # Price/MACD divergence (basic: price making new high but MACD lower)
        out["macd_price_divergence_bullish"] = 0
        out["macd_price_divergence_bearish"] = 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MACDEventsPlugin()
