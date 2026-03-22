"""trad_SecondLegContinuation — Fibonacci measured-move continuation evidence-contributor.

Fires when price has completed a significant swing (Leg 1) and has pulled back into the
38.2%-61.8% Fibonacci retracement zone, indicating the start of Leg 2.

Targets: 100%, 127.2%, 161.8% of Leg 1 amplitude beyond the entry.

Requires: HMM trend regime (1.0 = bullish, 2.0 = bearish). No signal in ranging markets.

Renaissance principles:
- Segment relentlessly: Fibonacci zone filters noise, targets measured moves precisely
- Earn the right through proof: amplitude gate (>= 1.0xATR) and regime gate required
- Instrument everything: fib_zone, amplitude, regime_prob captured in every signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_confluence_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import no_signal
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

    Gate 1: hmm_regime must be 1.0 (bullish) or 2.0 (bearish) — no ranging markets.
    Gate 2: swing amplitude >= 1.0×ATR.
    Gate 3: close must be in 38.2%-61.8% retracement zone of Leg 1.
    Gate 4: swing data not stale (both ages <= 50 bars).

    Targets computed as 100%, 127.2%, 161.8% of Leg 1 amplitude from entry.
    """

    name: str = "trad_SecondLegContinuation"
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=60),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}

        if df is None or len(df) < self.min_lookback:
            return {}

        # ── Price arrays ────────────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        # ── Regime gate ─────────────────────────────────────────────────────
        hmm_regime = float(features.get("hmm_regime", 0.0))
        if hmm_regime not in (1.0, 2.0):
            return no_signal()

        hmm_regime_prob = float(features.get("hmm_regime_prob", 0.0))

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
        fib_low = swing_high - _FIB_618 * amplitude   # 61.8% retrace (closer to low)
        # fib_low < fib_high always for bullish setup

        close_price = float(close[-1])

        if not (fib_low <= close_price <= fib_high):
            return no_signal()

        # ── Direction ───────────────────────────────────────────────────────
        # hmm_regime=1.0 → bullish trend → long continuation after pullback
        # hmm_regime=2.0 → bearish trend → short continuation after bounce
        direction = 1 if hmm_regime == 1.0 else -1

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

        # ── Confidence ───────────────────────────────────────────────────────
        raw_conf = 0.55
        if hmm_regime_prob > 0.75:
            raw_conf += 0.10

        # Bonus if close is near 50% retracement (ideal entry)
        dist_to_50 = abs(close_price - fib_50)
        zone_width = fib_high - fib_low
        if zone_width > 0 and dist_to_50 < 0.25 * zone_width:
            raw_conf += 0.05

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

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(frame.entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_confluence_features(
            features, direction, "trend", signal["confidence"]
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SecondLegContinuationPlugin()
