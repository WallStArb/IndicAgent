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
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25


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
    requires_i6_confluence: bool = True
    roc_period: int = 14
    roc_threshold: float = 0.3
    volume_expansion_threshold: float = 1.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        # ── Gate 1: continuous trending regime ────────────────────────────────
        if (
            hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT
            and hmm_regime_weight(features, "down") < _MIN_REGIME_WEIGHT
        ):
            return no_signal()

        # ── Gate 2: I6 ctf_score gate ─────────────────────────────────────────
        ctf_score = float(features.get("ctf_score") or 0.0)
        if abs(ctf_score) < _MIN_CTF_SCORE:
            return no_signal()

        # ── OHLCV extraction (after dual gate) ───────────────────────────────
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
        vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
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

        raw_conf = 0.40 * roc_score + 0.35 * vol_score + 0.25 * break_margin

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
            features_snapshot=capture_signal_features(features, direction, "trend", confidence),
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumBreakoutPlugin()
