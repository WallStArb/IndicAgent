"""trad_SecondLegContinuation — Fibonacci measured-move continuation evidence-contributor.

Fires when price has completed a significant swing (Leg 1) and has pulled back into the
38.2%-61.8% Fibonacci retracement zone, indicating the start of Leg 2.

Targets: 100%, 127.2%, 161.8% of Leg 1 amplitude beyond the entry.

HMM regime travels as an annotation, not an emission gate; direction is derived from
the dominant HMM trend (up vs down weight).

Renaissance principles:
- Segment relentlessly: Fibonacci zone filters noise, targets measured moves precisely
- Earn the right through proof: amplitude gate (>= 1.0xATR) required
- Instrument everything: fib_zone, amplitude, regime_prob captured in every signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    rel_volume_score,
)
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import build_features_from_tiers, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

# Fibonacci retracement levels for entry zone
_FIB_382 = 0.382
_FIB_618 = 0.618

# Measured-move target multipliers for Leg 2
_TARGET_100 = 1.000
_TARGET_1272 = 1.272
_TARGET_1618 = 1.618

# Maximum swing age before data is considered stale
_MAX_SWING_AGE_BARS = 50


@dataclass
class SecondLegContinuationPlugin:
    """I7 evidence contributor: fires on Fibonacci measured-move continuation setups.

    Gate 1: swing amplitude >= 1.0×ATR.
    Gate 2: close must be in 38.2%-61.8% retracement zone of Leg 1.
    Gate 3: swing data not stale (both ages <= 50 bars).

    Direction is derived from the dominant HMM trend (up vs down weight); HMM regime
    is an annotation, not an emission gate.

    Targets computed as 100%, 127.2%, 161.8% of Leg 1 amplitude from entry.
    """

    name: str = "trad_SecondLegContinuation"
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
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "fibonacci", "continuation", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=60),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = build_features_from_tiers(frames)

        if df is None or len(df) < self.min_lookback:
            return {}

        regime_up = hmm_regime_weight(features, "up")
        regime_down = hmm_regime_weight(features, "down")

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # ── Swing data ──────────────────────────────────────────────────────
        swing_high_raw = features.get("swing_high")
        swing_low_raw = features.get("swing_low")

        def _valid(v: Any) -> bool:
            return isinstance(v, (int, float)) and float(v) > 0

        if not (_valid(swing_high_raw) and _valid(swing_low_raw)):
            return no_signal()

        swing_high = float(swing_high_raw)
        swing_low = float(swing_low_raw)

        # ── Stale swing guard ───────────────────────────────────────────────
        swing_high_age = float(features.get("swing_high_age_bars", 999))
        swing_low_age = float(features.get("swing_low_age_bars", 999))
        if swing_high_age > _MAX_SWING_AGE_BARS and swing_low_age > _MAX_SWING_AGE_BARS:
            return no_signal()

        # ── Leg 1 amplitude ─────────────────────────────────────────────────
        amplitude = abs(swing_high - swing_low)
        if amplitude < 1.0 * atr:
            return no_signal()

        # ── Fibonacci zone for entry ─────────────────────────────────────────
        # Standard retracement: 38.2% retracement from high = swing_high - 0.382*amplitude
        #                       61.8% retracement from high = swing_high - 0.618*amplitude
        # Fib zone: price between these two retracement levels
        fib_high = swing_high - _FIB_382 * amplitude  # 38.2% retrace (closer to high)
        fib_low = swing_high - _FIB_618 * amplitude  # 61.8% retrace (closer to low)
        # fib_low < fib_high always for bullish setup

        # ── Price arrays ────────────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        close_price = float(close[-1])

        if not (fib_low <= close_price <= fib_high):
            return no_signal()

        # ── Direction: dominant trending regime determines continuation ──────
        # Use the stronger of up/down regime weight
        direction = 1 if regime_up >= regime_down else -1

        # ── Entry: 50% retracement midpoint ─────────────────────────────────
        fib_50 = (swing_high + swing_low) / 2
        entry_price = fib_50

        # ── Signal type ─────────────────────────────────────────────────────
        signal_type = "second_leg_long" if direction == 1 else "second_leg_short"

        # ── Trade frame ──────────────────────────────────────────────────────
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry_price,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )
        if not frame.viable:
            return no_signal()

        # ── Measured-move targets ────────────────────────────────────────────
        # Override frame targets with measured-move Fibonacci extensions
        # T1 = entry + 1.0×amplitude, T2 = entry + 1.272×amplitude, T3 = entry + 1.618×amplitude
        if direction == 1:
            t1 = round(entry_price + _TARGET_100 * amplitude, 2)
            t2 = round(entry_price + _TARGET_1272 * amplitude, 2)
            t3 = round(entry_price + _TARGET_1618 * amplitude, 2)
        else:
            t1 = round(entry_price - _TARGET_100 * amplitude, 2)
            t2 = round(entry_price - _TARGET_1272 * amplitude, 2)
            t3 = round(entry_price - _TARGET_1618 * amplitude, 2)

        targets = [t1, t2, t3]

        # ── 4-factor confidence composite (NO HMM probability) ───────────────
        # leg_quality_score: amplitude vs ATR (larger measured move = higher quality)
        leg_quality_score = clamp01((amplitude / atr - 1.0) / 3.0) if atr > 0 else 0.5

        # momentum_persistence_score: how fresh are the swings? (lower age = higher score)
        best_age = min(swing_high_age, swing_low_age)
        momentum_persistence_score = clamp01(1.0 - best_age / _MAX_SWING_AGE_BARS)

        # volume_alignment_score: volume expansion confirmation
        volume_alignment_score = rel_volume_score(features)

        # structure_quality_score: how close to the ideal 50% retracement entry?
        zone_width = fib_high - fib_low
        dist_to_50 = abs(close_price - fib_50)
        structure_quality_score = (
            clamp01(1.0 - dist_to_50 / (zone_width / 2.0)) if zone_width > 0 else 0.5
        )

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "leg_quality_score": round(leg_quality_score, 4),
            "momentum_persistence_score": round(momentum_persistence_score, 4),
            "volume_alignment_score": round(volume_alignment_score, 4),
            "structure_quality_score": round(structure_quality_score, 4),
        }

        # Weights: 0.35 + 0.30 + 0.20 + 0.15 = 1.0
        raw_conf = (
            0.35 * leg_quality_score
            + 0.30 * momentum_persistence_score
            + 0.20 * volume_alignment_score
            + 0.15 * structure_quality_score
        )

        supporting = [
            f"swing_high={swing_high:.2f}",
            f"swing_low={swing_low:.2f}",
            f"amplitude={amplitude:.2f}",
            f"fib_zone=[{fib_low:.2f},{fib_high:.2f}]",
            f"close={close_price:.2f}",
        ]
        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        # ── Regime context ───────────────────────────────────────────────────
        regime_ctx = "bullish" if direction == 1 else "bearish"

        signal = make_signal_from_frame(
            frame,
            symbol="",
            timeframe="",
            timestamp="",
            signal_type=signal_type,
            setup_plugin="trad_SecondLegContinuation",
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        signal["targets"] = targets
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SecondLegContinuationPlugin()
