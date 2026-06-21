"""I7 VWAP Deviation setup detection plugin.

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
    compose_confidence,
)
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import build_features_from_tiers, extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_VOL_THRESHOLDS: dict[int, float] = {0: 2.0, 1: 2.0, 2: 2.5, 3: 3.0}


@dataclass
class VWAPDeviationPlugin:
    """VWAP Deviation setup: fires when price extends >2σ from session VWAP.

    Reads vwap, vwap_upper_2, vwap_lower_2, vwap_std from I1 VWAP plugin.
    Long when price < vwap_lower_2, short when price > vwap_upper_2.
    Targets: T1 = VWAP (the mean), T2 = opposite 1σ band.
    Confidence: deviation magnitude, regime compatibility, volume contraction.
    """

    name: str = "trad_VWAPDeviation"
    shadow_only: bool = True
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
    capability_tags: frozenset[str] = frozenset({"trading", "vwap", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    sigma_threshold: float = 2.0
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        features = build_features_from_tiers(frames)

        # ── VWAP features ──
        vwap = features.get("vwap", 0.0)
        vwap_std = features.get("vwap_std", 0.0)

        # Gate: VWAP must be meaningful (session has volume)
        if vwap_std <= 0 or vwap <= 0:
            return no_signal()

        # ── OHLCV extraction ─────────────────────────────────────────────────
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # Gate: price must be outside dynamic sigma threshold (GARCH-adaptive)
        vol_regime = int(features.get("garch_vol_regime", 1))
        effective_threshold = _VOL_THRESHOLDS.get(vol_regime, 2.0)
        sigma_deviation = abs(price - vwap) / vwap_std
        if sigma_deviation < effective_threshold:
            return no_signal()

        # Direction
        direction = 1 if price < vwap else -1

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = price

        # ── Confidence ──

        # Deviation score (0.40): sigma excess beyond 2σ, capped at 4σ
        sigma_deviation = abs(price - vwap) / vwap_std
        dev_score = min(1.0, max(0.0, (sigma_deviation - 2.0) / 2.0))

        # Regime compatibility (0.35): trend_regime aligned with reversion direction
        trend_regime = features.get("trend_regime", 0.0)
        regime_aligns = (direction == 1 and trend_regime > 0) or (
            direction == -1 and trend_regime < 0
        )
        if abs(trend_regime) < 0.3:
            regime_compat = 0.50
        elif regime_aligns:
            regime_compat = 0.70 + 0.30 * abs(trend_regime)
        else:
            regime_compat = max(0.0, 0.50 - abs(trend_regime))

        # Volume contraction (0.25): lower volume = better fade
        vol_sma = float(np.mean(volume[-21:-1])) if len(volume) >= 2 else 0.0
        volume_ratio = float(volume[-1]) / vol_sma if vol_sma > 0 else 1.0
        vol_contraction = max(0.0, 1.0 - max(0.0, volume_ratio - 1.0))

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "dev_score": round(dev_score, 4),
            "regime_compat": round(regime_compat, 4),
            "vol_contraction": round(vol_contraction, 4),
        }

        raw_conf = 0.40 * dev_score + 0.35 * regime_compat + 0.25 * vol_contraction

        # Supporting factors
        supporting = ["vwap_2sigma_breach", f"vwap_{sigma_deviation:.1f}sigma_deviation"]
        if abs(trend_regime) < 0.3:
            supporting.append("ranging_regime")
        if volume_ratio < 1.0:
            supporting.append("low_volume_deviation")
        if regime_aligns and abs(trend_regime) >= 0.3:
            supporting.append("regime_aligned")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        signal_type = "vwap_reversion_long" if direction == 1 else "vwap_reversion_short"
        regime_ctx = "vwap_extended_low" if direction == 1 else "vwap_extended_high"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
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


plugin = VWAPDeviationPlugin()
