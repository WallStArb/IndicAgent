"""I7 SqueezeExpansion setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import extract_ohlcv, no_signal


@dataclass
class SqueezeExpansionPlugin:
    """Squeeze-expansion setup: fires when BB squeeze (I5) has just released with volume expansion.

    Reads I5 squeeze_fired/squeeze_active/squeeze_bars, I4 momentum_bias,
    I1 bb_upper/bb_lower/bb_middle/atr_14/volume_sma_20 from frames["features"].
    Direction from momentum_bias or close vs bb_middle fallback.
    Targets based on measured move from squeeze range.
    """

    name: str = "trad_SqueezeExpansion"
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
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "squeeze", "volatility"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
    volume_expansion_threshold: float = 1.3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        # Gate: squeeze must have just released
        squeeze_fired = features.get("squeeze_fired", 0.0)
        squeeze_active = features.get("squeeze_active", 0.0)
        if squeeze_fired != 1.0 or squeeze_active != 0.0:
            return no_signal()

        # Gate: volume expansion
        df = frames.get("main")
        volume = df["volume"].to_numpy(dtype=float)
        current_volume = float(volume[-1])

        volume_sma_20 = features.get("volume_sma_20")
        if volume_sma_20 is None or volume_sma_20 <= 0:
            if len(volume) >= 20:
                volume_sma_20 = float(np.mean(volume[-20:]))
            else:
                volume_sma_20 = float(np.mean(volume))
        if volume_sma_20 <= 0:
            return no_signal()

        volume_ratio = current_volume / volume_sma_20
        if current_volume <= volume_sma_20 * self.volume_expansion_threshold:
            return no_signal()

        # ── Gate: block in extreme GARCH vol regime (regime=3, top 5th pctile) ──
        vol_regime = int(features.get("garch_vol_regime", 1))
        if vol_regime == 3:
            return no_signal()

        # Direction from momentum_bias, fallback to close vs bb_middle
        momentum_bias = features.get("momentum_bias", 0.0)
        bb_middle = features.get("bb_20_2_mid", 0.0)
        bb_upper = features.get("bb_20_2_upper", 0.0)
        bb_lower = features.get("bb_20_2_lower", 0.0)
        squeeze_bars = features.get("squeeze_bars", 0.0)
        trend_regime = features.get("trend_regime", 0.0)

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        if momentum_bias != 0.0:
            direction = 1 if momentum_bias > 0 else -1
        elif bb_middle > 0:
            direction = 1 if close[-1] > bb_middle else -1
        else:
            return no_signal()

        # Entry
        entry = float(close[-1])

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

        # Regime clarity (0.2): continuous HMM trending probability
        if trend_regime != 0.0:
            regime_agrees = (trend_regime > 0 and direction == 1) or (
                trend_regime < 0 and direction == -1
            )
            if regime_agrees:
                regime_score = 0.2 + 0.6 * max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
            else:
                regime_score = 0.2
        else:
            regime_score = 0.5

        raw_conf = (
            0.3 * squeeze_bars_score
            + 0.3 * vol_expansion_score
            + 0.2 * momentum_score
            + 0.2 * regime_score
        )

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

        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        signal_type = "squeeze_long" if direction == 1 else "squeeze_short"
        regime_ctx = "expansion_bullish" if direction == 1 else "expansion_bearish"

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
        signal["_shadow"] = capture_signal_features(
            features, direction, "trend", signal["confidence"]
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SqueezeExpansionPlugin()
