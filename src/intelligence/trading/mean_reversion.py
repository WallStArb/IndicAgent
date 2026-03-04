"""I7 Mean Reversion setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class MeanReversionPlugin:
    """Mean-reversion setup: fires when regime = ranging + price at RSI extreme or divergence.

    Gates on |trend_regime| < 0.4 (must NOT be trending).
    Long when RSI < 35 or bullish divergence present.
    Short when RSI > 65 or bearish divergence present.
    Targets Bollinger middle band and nearest S/R levels.
    """

    name: str = "trad_MeanReversion"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    regime_type: str = "mean_reversion"
    regime_threshold: float = 0.4
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # ── Gate: must be ranging (not trending) ──
        trend_regime = features.get("trend_regime", 0.0)
        if abs(trend_regime) >= self.regime_threshold:
            return self._no_signal()

        # ── Gate: price must be displaced from Kalman fair value ──
        kalman_pos = features.get("kalman_price_position")
        if kalman_pos is not None and abs(float(kalman_pos)) < 1.0:
            return self._no_signal()

        # ── Read features ──
        rsi = features.get("rsi_14", 50.0)
        rsi_div_bull = features.get("rsi_div_bullish", 0.0)
        rsi_div_bear = features.get("rsi_div_bearish", 0.0)
        vol_regime = features.get("vol_regime", 0.5)
        bb_middle = features.get("bb_20_2_mid", None)
        sr_support = features.get("sr_nearest_support", None)
        sr_resistance = features.get("sr_nearest_resistance", None)
        atr = features.get("atr_14", 0.0)

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        price = float(close[-1])

        # Fallback ATR
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

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
            return self._no_signal()

        entry = price

        # ── Stop loss ──
        if direction == 1:
            if sr_support is not None and sr_support > 0:
                stop = sr_support - atr * 0.5
            else:
                stop = entry - atr * 2.0
        else:
            if sr_resistance is not None and sr_resistance > 0:
                stop = sr_resistance + atr * 0.5
            else:
                stop = entry + atr * 2.0

        # ── Targets ──
        t1 = bb_middle if bb_middle is not None and bb_middle > 0 else (
            entry + atr if direction == 1 else entry - atr
        )
        if direction == 1:
            t2 = (
                sr_resistance if sr_resistance is not None and sr_resistance > 0
                else entry + atr * 2.0
            )
        else:
            t2 = (
                sr_support if sr_support is not None and sr_support > 0
                else entry - atr * 2.0
            )
        targets = [round(float(t1), 2), round(float(t2), 2)]

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

        raw_conf = (
            0.3 * rsi_extreme
            + 0.3 * div_score
            + 0.2 * vol_stability
            + 0.2 * sr_prox
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

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

        signal_type = "reversion_long" if direction == 1 else "reversion_short"
        regime_ctx = "ranging"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = MeanReversionPlugin()
