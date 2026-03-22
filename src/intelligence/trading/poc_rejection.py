"""trad_POCRejection — I7 mean-reversion setup consuming I4 VolumeProfile POC field.

Fires when price tests the Point of Control (highest volume price level) and
shows momentum reversal, expecting price to be repelled from the POC.

Renaissance principles:
- Segment relentlessly: fires only in mean-reversion context (hmm_regime=0 preferred)
- Instrument everything: POC test volume ratio logged for training data
- Earn the right through proof: dual gate (proximity + reversal) required
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .trade_framer import frame_trade

# Maximum ATR distance from POC to qualify as "testing" the level
_POC_PROXIMITY_ATR = 0.3

# Minimum divergence confidence to count as reversal
_DIV_THRESHOLD = 0.3

# Stochastic overbought/oversold thresholds
_STOCH_OVERSOLD = 30.0
_STOCH_OVERBOUGHT = 70.0


@dataclass
class POCRejectionPlugin:
    """Mean-reversion setup: price tests POC with momentum reversal confirmation.

    Gates:
    - poc_price and atr_14 available
    - abs(close - poc_price) / atr_14 < 0.3 (within 0.3 ATR of POC)
    - Reversal gate: rsi_div_bullish > 0.3 OR stoch_k < 30 (long)
                     rsi_div_bearish > 0.3 OR stoch_k > 70 (short)

    Direction: long if close < poc_price (approaching from below), short if close > poc_price
    """

    name: str = "trad_POCRejection"
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
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "mean_reversion"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        timeframe = frames.get("timeframe", "")
        if timeframe and timeframe not in ("1m", "5m", "15m"):
            return no_signal()

        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Required: POC price ───────────────────────────────────────────────
        poc_price = features.get("poc_price")
        if poc_price is None:
            return no_signal()
        poc_price = float(poc_price)
        if poc_price <= 0:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        # ── Close price ───────────────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # ── Proximity gate ────────────────────────────────────────────────────
        if abs(entry - poc_price) / atr >= _POC_PROXIMITY_ATR:
            return no_signal()

        # ── Direction: long if below POC, short if above ──────────────────────
        direction = 1 if entry < poc_price else -1

        # ── Momentum reversal gate ────────────────────────────────────────────
        rsi_div_bullish = float(features.get("rsi_div_bullish", 0.0))
        rsi_div_bearish = float(features.get("rsi_div_bearish", 0.0))
        stoch_k = float(features.get("stoch_k_14_3", 50.0))

        if direction == 1:
            rsi_div_ok = rsi_div_bullish > _DIV_THRESHOLD
            stoch_ok = stoch_k < _STOCH_OVERSOLD
            reversal_ok = rsi_div_ok or stoch_ok
            reversal_strength = max(
                rsi_div_bullish, (30.0 - stoch_k) / 30.0 if stoch_k < 30 else 0.0
            )
        else:
            rsi_div_ok = rsi_div_bearish > _DIV_THRESHOLD
            stoch_ok = stoch_k > _STOCH_OVERBOUGHT
            reversal_ok = rsi_div_ok or stoch_ok
            reversal_strength = max(
                rsi_div_bearish, (stoch_k - 70.0) / 30.0 if stoch_k > 70 else 0.0
            )

        if not reversal_ok:
            return no_signal()

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "poc_rejection_long" if direction == 1 else "poc_rejection_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            return no_signal()

        # ── POC test volume ratio ─────────────────────────────────────────────
        bar_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].mean())
        poc_test_volume_ratio = (bar_vol / avg_vol) if avg_vol > 0 else 1.0

        # ── Confidence scoring ────────────────────────────────────────────────
        # Proximity to POC: 0.3 weight — closer = higher conviction
        dist_ratio = abs(entry - poc_price) / (atr * _POC_PROXIMITY_ATR)
        proximity_score = max(0.0, 1.0 - dist_ratio)

        # Reversal strength: 0.3 weight
        reversal_score = min(1.0, max(0.0, reversal_strength))

        # Volume at test: 0.2 weight
        vol_score = min(1.0, max(0.0, poc_test_volume_ratio - 1.0))

        # VA width inverse: 0.2 weight (tighter = more significant POC)
        va_width_atr = float(features.get("va_width_atr", 2.0))
        va_inverse = max(0.0, 1.0 - va_width_atr / 4.0)

        raw_conf = (
            0.30 * proximity_score
            + 0.30 * reversal_score
            + 0.20 * vol_score
            + 0.20 * va_inverse
        )

        # ── Supporting factors ────────────────────────────────────────────────
        supporting: list[str] = [
            f"poc_price={poc_price:.2f}",
            f"poc_distance_atr={abs(entry - poc_price) / atr:.3f}",
            f"poc_test_volume_ratio={poc_test_volume_ratio:.2f}",
        ]
        if rsi_div_ok:
            div_label = "rsi_div_bullish" if direction == 1 else "rsi_div_bearish"
            supporting.append(div_label)
        if stoch_ok:
            supporting.append(f"stoch_extreme={stoch_k:.1f}")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        hmm = float(features.get("hmm_regime", 0.0))
        regime_ctx = "ranging" if hmm == 0 else ("trending_up" if hmm == 1 else "trending_down")

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": [round(t.price, 2) for t in frame.targets],
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "mean_reversion", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = POCRejectionPlugin()
