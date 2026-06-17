"""trad_POCRejection — I7 mean-reversion setup consuming I4 VolumeProfile POC field.

Fires when price tests the Point of Control (highest volume price level) and
shows momentum reversal, expecting price to be repelled from the POC.

Renaissance principles:
- Segment relentlessly: fires only in mean-reversion context (hmm_regime=0 preferred)
- Instrument everything: POC test volume ratio logged for training data
- Earn the right through proof: dual gate (proximity + reversal) required
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade
from .volume_profile_utils import (
    check_reversal_gate,
    format_reversal_supporting_factors,
    get_div_threshold,
    get_stoch_overbought,
    get_stoch_oversold,
)

# Maximum ATR distance from POC to qualify as "testing" the level
_POC_PROXIMITY_ATR = 0.3


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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
    regime_type: str = "mean_reversion"
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        proximity_atr = (
            cfg.get_sync("threshold.poc_rejection.proximity_atr", _POC_PROXIMITY_ATR)
            if cfg
            else _POC_PROXIMITY_ATR
        )
        timeframe = frames.get("timeframe", "")
        if timeframe and timeframe not in ("1m", "5m", "15m"):
            return no_signal()

        df = frames.get("main")
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Required: POC price ───────────────────────────────────────────────
        poc_price = features.get("poc_price")
        if poc_price is None:
            return no_signal()
        poc_price = float(poc_price)
        if poc_price <= 0:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # ── Close price ───────────────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # ── Proximity gate ────────────────────────────────────────────────────
        if abs(entry - poc_price) / atr >= proximity_atr:
            return no_signal()

        # ── Direction: long if below POC, short if above ──────────────────────
        direction = 1 if entry < poc_price else -1

        # ── Momentum reversal gate ────────────────────────────────────────────
        reversal_ok, reversal_strength = check_reversal_gate(features, direction)

        if not reversal_ok:
            return no_signal()

        # Extract RSI/stoch flags for supporting factors
        rsi_div_bullish = float(features.get("rsi_div_bullish", 0.0))
        rsi_div_bearish = float(features.get("rsi_div_bearish", 0.0))
        stoch_k = float(features.get("stoch_k_14_3", 50.0))
        div_threshold = get_div_threshold()
        stoch_oversold = get_stoch_oversold()
        stoch_overbought = get_stoch_overbought()

        rsi_div_ok = (direction == 1 and rsi_div_bullish > div_threshold) or (
            direction == -1 and rsi_div_bearish > div_threshold
        )
        stoch_ok = (direction == 1 and stoch_k < stoch_oversold) or (
            direction == -1 and stoch_k > stoch_overbought
        )

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "poc_rejection_long" if direction == 1 else "poc_rejection_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )
        if not frame.viable:
            return no_signal()

        # ── POC test volume ratio ─────────────────────────────────────────────
        bar_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else 0.0
        poc_test_volume_ratio = (bar_vol / avg_vol) if avg_vol > 0 else 1.0

        # ── Confidence scoring ────────────────────────────────────────────────
        # Proximity to POC: 0.3 weight — closer = higher conviction
        dist_ratio = abs(entry - poc_price) / (atr * proximity_atr)
        proximity_score = max(0.0, 1.0 - dist_ratio)

        # Reversal strength: 0.3 weight
        reversal_score = min(1.0, max(0.0, reversal_strength))

        # Volume at test: 0.2 weight
        vol_score = min(1.0, max(0.0, poc_test_volume_ratio - 1.0))

        # VA width inverse: 0.2 weight (tighter = more significant POC)
        va_width_atr = float(features.get("va_width_atr") or 2.0)
        va_inverse = max(0.0, 1.0 - va_width_atr / 4.0)

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "proximity_score": round(proximity_score, 4),
            "reversal_score": round(reversal_score, 4),
            "vol_score": round(vol_score, 4),
            "va_inverse": round(va_inverse, 4),
        }

        raw_conf = (
            0.30 * proximity_score + 0.30 * reversal_score + 0.20 * vol_score + 0.20 * va_inverse
        )

        # ── Supporting factors ────────────────────────────────────────────────
        supporting: list[str] = [
            f"poc_price={poc_price:.2f}",
            f"poc_distance_atr={abs(entry - poc_price) / atr:.3f}",
            f"poc_test_volume_ratio={poc_test_volume_ratio:.2f}",
        ]
        supporting.extend(
            format_reversal_supporting_factors(features, direction, rsi_div_ok, stoch_ok)
        )

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        hmm = float(features.get("hmm_regime") or 0.0)
        regime_ctx = "ranging" if hmm == 0 else ("trending_up" if hmm == 1 else "trending_down")

        signal = make_signal_from_frame(
            frame,
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
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = POCRejectionPlugin()
