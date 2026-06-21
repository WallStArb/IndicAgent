"""I7 Momentum Breakout setup detection plugin.

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
from .plugin_utils import build_features_from_tiers, extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class MomentumBreakoutPlugin:
    """Momentum breakout setup: fires on ROC spike + volume expansion + structure break.

    All three gates are required (triple-gate sequential). Any failure → no signal.
    ROC direction must match structure break direction.
    Stop is placed at the broken structure level (new S/R), not from entry price.
    """

    name: str = "trad_MomentumBreakout"
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
    capability_tags: frozenset[str] = frozenset({"trading", "breakout", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    roc_period: int = 14
    roc_threshold: float = 0.3
    volume_expansion_threshold: float = 1.5
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        features = build_features_from_tiers(frames)

        # ── OHLCV extraction ─────────────────────────────────────────────────
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # ── Gate A: ROC spike ──
        # Use pipeline feature if available (ROC_PPO in I1_PLUGINS), else compute inline
        roc = features.get(f"roc_{self.roc_period}")
        if roc is None:
            if len(close) > self.roc_period:
                past = float(close[-1 - self.roc_period])
                roc = (price - past) / past * 100.0 if past != 0 else 0.0
            else:
                return no_signal()

        if abs(roc) <= self.roc_threshold:
            return no_signal()

        # ── Gate B: volume expansion ──
        vol_sma = features.get("volume_sma_20")
        if vol_sma is None or float(vol_sma) <= 0:
            # Exclude the current bar from the baseline to avoid self-inflation.
            vol_sma = float(np.mean(volume[-21:-1]))
        else:
            vol_sma = float(vol_sma)
        if vol_sma <= 0:
            return no_signal()
        volume_ratio = float(volume[-1]) / vol_sma
        if volume_ratio <= self.volume_expansion_threshold:
            return no_signal()

        # ── Gate C + direction: structure break must match ROC direction ──
        swing_high = features.get("swing_high", 0.0)
        swing_low = features.get("swing_low", 0.0)

        if roc > 0:
            if swing_high <= 0 or price <= swing_high:
                return no_signal()
            direction = 1
            structure_level = float(swing_high)
        else:
            if swing_low <= 0 or price >= swing_low:
                return no_signal()
            direction = -1
            structure_level = float(swing_low)

        # ── ATR ──
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = price

        # ── Confidence (3-factor, unchanged per plan) ──
        roc_score = clamp01((abs(roc) - self.roc_threshold) / self.roc_threshold)
        vol_score = clamp01(
            (volume_ratio - self.volume_expansion_threshold) / self.volume_expansion_threshold
        )
        break_margin = clamp01(abs(price - structure_level) / atr)

        cfg = self._config_service
        w_roc = cfg.get_sync("weights.momentum_breakout.roc", 0.40) if cfg else 0.40
        w_vol = cfg.get_sync("weights.momentum_breakout.vol", 0.35) if cfg else 0.35
        w_margin = cfg.get_sync("weights.momentum_breakout.break_margin", 0.25) if cfg else 0.25
        _validate_weights_sum(
            {"roc": w_roc, "vol": w_vol, "break_margin": w_margin},
            "trad_MomentumBreakout",
        )
        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "roc_score": round(roc_score, 4),
            "vol_score": round(vol_score, 4),
            "break_margin": round(break_margin, 4),
        }

        raw_conf = w_roc * roc_score + w_vol * vol_score + w_margin * break_margin

        # Supporting factors
        supporting = [
            f"roc_spike_{abs(roc):.1f}pct",
            f"volume_{volume_ratio:.1f}x_expansion",
            "structure_break_long" if direction == 1 else "structure_break_short",
        ]
        confidence = compose_confidence(raw_conf)

        signal_type = "momentum_breakout_long" if direction == 1 else "momentum_breakout_short"
        regime_ctx = "breakout_bullish" if direction == 1 else "breakout_bearish"

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


plugin = MomentumBreakoutPlugin()
