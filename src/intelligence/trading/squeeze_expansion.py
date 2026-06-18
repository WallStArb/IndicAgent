"""I7 SqueezeExpansion setup detection plugin.

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    _validate_weights_sum,
    clamp01,
    compose_confidence,
)
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    shadow_only: bool = True
    volume_expansion_threshold: float = 1.3
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

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
            volume_sma_20 = float(np.mean(volume[-21:-1])) if len(volume) >= 2 else 0.0
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
        squeeze_bars = features.get("squeeze_duration", 0.0)
        trend_regime = features.get("trend_regime", 0.0)

        atr = get_atr_with_floor_from_frames(frames)
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

        # Confidence scoring
        # Squeeze bars duration (0.35): longer squeeze = stronger, cap at 30 bars
        squeeze_bars_score = clamp01(squeeze_bars / 30.0)

        # Volume expansion ratio (0.35): cap at 3x
        vol_expansion_score = clamp01((volume_ratio - 1.0) / 2.0)

        # Momentum clarity (0.30): abs(momentum_bias), capped at 1.0
        momentum_score = clamp01(abs(momentum_bias))

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "squeeze_bars_score": round(squeeze_bars_score, 4),
            "vol_expansion_score": round(vol_expansion_score, 4),
            "momentum_score": round(momentum_score, 4),
        }

        cfg = self._config_service
        w_sq = cfg.get_sync("weights.squeeze_expansion.squeeze_bars", 0.35) if cfg else 0.35
        w_vol = cfg.get_sync("weights.squeeze_expansion.vol_expansion", 0.35) if cfg else 0.35
        w_mom = cfg.get_sync("weights.squeeze_expansion.momentum", 0.30) if cfg else 0.30
        _validate_weights_sum(
            {"squeeze_bars": w_sq, "vol_expansion": w_vol, "momentum": w_mom},
            "trad_SqueezeExpansion",
        )
        raw_conf = w_sq * squeeze_bars_score + w_vol * vol_expansion_score + w_mom * momentum_score

        # Supporting factors
        supporting = []
        supporting.append(f"squeeze_{int(squeeze_bars)}_bars")
        supporting.append(f"volume_{volume_ratio:.1f}x_expansion")
        if abs(momentum_bias) >= 0.5:
            supporting.append("strong_momentum")

        confidence = compose_confidence(raw_conf)

        signal_type = "squeeze_long" if direction == 1 else "squeeze_short"
        regime_ctx = "expansion_bullish" if direction == 1 else "expansion_bearish"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", "") or frames.get("__symbol__", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SqueezeExpansionPlugin()
