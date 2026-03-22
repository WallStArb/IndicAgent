"""I7 Mean Reversion setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_confluence_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .trade_framer import frame_trade


@dataclass
class MeanReversionPlugin:
    """Mean-reversion setup: fires when regime = ranging + price at RSI extreme or divergence.

    Gates on |trend_regime| < 0.4 (must NOT be trending).
    Long when RSI < 35 or bullish divergence present.
    Short when RSI > 65 or bearish divergence present.
    Targets Bollinger middle band and nearest S/R levels.
    """

    name: str = "trad_MeanReversion"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    regime_threshold: float = 0.4
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        # ── Gate: must be ranging (not trending) ──
        trend_regime = features.get("trend_regime", 0.0)
        if abs(trend_regime) >= self.regime_threshold:
            return no_signal()

        # ── Gate: price must be displaced from Kalman fair value ──
        kalman_pos = features.get("kalman_price_position")
        if kalman_pos is not None and abs(float(kalman_pos)) < 1.0:
            return no_signal()

        # ── Read features ──
        rsi = features.get("rsi_14", 50.0)
        rsi_div_bull = features.get("rsi_div_bullish", 0.0)
        rsi_div_bear = features.get("rsi_div_bearish", 0.0)
        vol_regime = features.get("vol_regime", 0.5)
        sr_support = features.get("sr_nearest_support", None)
        sr_resistance = features.get("sr_nearest_resistance", None)

        price = float(close[-1])

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        # ── Direction detection ──
        long_rsi = rsi < 35
        long_div = rsi_div_bull > 0.3
        short_rsi = rsi > 65
        short_div = rsi_div_bear > 0.3

        if long_rsi or long_div:
            direction = 1
        elif short_rsi or short_div:
            direction = -1
        else:
            return no_signal()

        entry = price
        signal_type = signal_type_for_direction("reversion", direction)

        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        stop = tf.stop
        targets = [round(t.price, 2) for t in tf.targets]

        # ── Confidence scoring ──
        # RSI extremeness (0.3 weight)
        if direction == 1:
            rsi_extreme = min(1.0, max(0.0, (35.0 - rsi) / 35.0)) if rsi < 35 else 0.0
        else:
            rsi_extreme = min(1.0, max(0.0, (rsi - 65.0) / 35.0)) if rsi > 65 else 0.0

        # Divergence (0.3 weight)
        div_score = min(1.0, rsi_div_bull if direction == 1 else rsi_div_bear)

        # Vol regime stability (0.2 weight) — closer to 0.5 = more stable ranging
        vol_stability = 1.0 - min(1.0, abs(vol_regime - 0.5) * 2.0)

        # S/R proximity (0.2 weight)
        if direction == 1 and sr_support is not None and sr_support > 0:
            sr_prox = max(0.0, 1.0 - abs(price - sr_support) / (atr * 3.0))
        elif direction == -1 and sr_resistance is not None and sr_resistance > 0:
            sr_prox = max(0.0, 1.0 - abs(price - sr_resistance) / (atr * 3.0))
        else:
            sr_prox = 0.0

        raw_conf = 0.3 * rsi_extreme + 0.3 * div_score + 0.2 * vol_stability + 0.2 * sr_prox

        # ── Supporting factors ──
        supporting = []
        if long_rsi or short_rsi:
            supporting.append("rsi_extreme")
        if long_div or short_div:
            supporting.append("rsi_divergence")
        if sr_prox > 0.3:
            supporting.append("near_sr_level")
        if vol_stability > 0.5:
            supporting.append("stable_vol_regime")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "ranging"

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_confluence_features(
            features, direction, "mean_reversion", confidence,
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MeanReversionPlugin()
