"""I7 SqueezeExpansion setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class SqueezeExpansionPlugin:
    """Squeeze-expansion setup: fires when BB squeeze (I5) has just released with volume expansion.

    Reads I5 squeeze_fired/squeeze_active/squeeze_bars, I4 momentum_bias,
    I1 bb_upper/bb_lower/bb_middle/atr_14/volume_sma_20 from frames["features"].
    Direction from momentum_bias or close vs bb_middle fallback.
    Targets based on measured move from squeeze range.
    """

    name: str = "trad_SqueezeExpansion"
    outputs: set[str] = frozenset(
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
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "squeeze", "volatility"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
    volume_expansion_threshold: float = 1.3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # Gate: squeeze must have just released
        squeeze_fired = features.get("squeeze_fired", 0.0)
        squeeze_active = features.get("squeeze_active", 0.0)
        if squeeze_fired != 1.0 or squeeze_active != 0.0:
            return self._no_signal()

        # Gate: volume expansion
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        current_volume = float(volume[-1])

        volume_sma_20 = features.get("volume_sma_20")
        if volume_sma_20 is None or volume_sma_20 <= 0:
            if len(volume) >= 20:
                volume_sma_20 = float(np.mean(volume[-20:]))
            else:
                volume_sma_20 = float(np.mean(volume))
        if volume_sma_20 <= 0:
            return self._no_signal()

        volume_ratio = current_volume / volume_sma_20
        if current_volume <= volume_sma_20 * self.volume_expansion_threshold:
            return self._no_signal()

        # ── Gate: block in extreme GARCH vol regime (regime=3, top 5th pctile) ──
        vol_regime = int(features.get("garch_vol_regime", 1))
        if vol_regime == 3:
            return self._no_signal()

        # Direction from momentum_bias, fallback to close vs bb_middle
        momentum_bias = features.get("momentum_bias", 0.0)
        bb_middle = features.get("bb_20_2_mid", 0.0)
        bb_upper = features.get("bb_20_2_upper", 0.0)
        bb_lower = features.get("bb_20_2_lower", 0.0)
        atr = features.get("atr_14", 0.0)
        squeeze_bars = features.get("squeeze_bars", 0.0)
        trend_regime = features.get("trend_regime", 0.0)

        if momentum_bias != 0.0:
            direction = 1 if momentum_bias > 0 else -1
        elif bb_middle > 0:
            direction = 1 if close[-1] > bb_middle else -1
        else:
            return self._no_signal()

        # Entry
        entry = float(close[-1])

        # ATR fallback
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Stop loss
        if direction == 1:
            stop = min(bb_lower, entry - atr * 1.5) if bb_lower > 0 else entry - atr * 1.5
        else:
            stop = max(bb_upper, entry + atr * 1.5) if bb_upper > 0 else entry + atr * 1.5

        # Targets: measured move from squeeze range
        measured_move = bb_upper - bb_lower if bb_upper > bb_lower else atr * 2.0
        if direction == 1:
            targets = [
                round(entry + measured_move * 0.5, 2),
                round(entry + measured_move, 2),
                round(entry + measured_move * 1.5, 2),
            ]
        else:
            targets = [
                round(entry - measured_move * 0.5, 2),
                round(entry - measured_move, 2),
                round(entry - measured_move * 1.5, 2),
            ]

        # Confidence scoring
        # Squeeze bars duration (0.3): longer squeeze = stronger, cap at 30 bars
        squeeze_bars_score = min(1.0, squeeze_bars / 30.0) if squeeze_bars > 0 else 0.0

        # Volume expansion ratio (0.3): cap at 3x
        vol_expansion_score = min(1.0, (volume_ratio - 1.0) / 2.0)

        # Momentum clarity (0.2): abs(momentum_bias), capped at 1.0
        momentum_score = min(1.0, abs(momentum_bias))

        # Regime clarity (0.2): not conflicting with direction
        if trend_regime != 0.0:
            regime_agrees = (trend_regime > 0 and direction == 1) or (
                trend_regime < 0 and direction == -1
            )
            regime_score = 0.8 if regime_agrees else 0.2
        else:
            regime_score = 0.5

        raw_conf = (
            0.3 * squeeze_bars_score
            + 0.3 * vol_expansion_score
            + 0.2 * momentum_score
            + 0.2 * regime_score
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # Supporting factors
        supporting = []
        supporting.append(f"squeeze_{int(squeeze_bars)}_bars")
        supporting.append(f"volume_{volume_ratio:.1f}x_expansion")
        if abs(momentum_bias) >= 0.5:
            supporting.append("strong_momentum")
        if trend_regime != 0.0 and (
            (trend_regime > 0 and direction == 1) or (trend_regime < 0 and direction == -1)
        ):
            supporting.append("regime_aligned")

        signal_type = "squeeze_long" if direction == 1 else "squeeze_short"
        regime_ctx = "expansion_bullish" if direction == 1 else "expansion_bearish"

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


plugin = SqueezeExpansionPlugin()
