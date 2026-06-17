"""trad_HVNRejection — I7 mean-reversion setup consuming I4 VolumeProfile HVN fields.

Fires when price approaches a High Volume Node (area of strong historical
acceptance) and shows momentum reversal. HVNs act as magnetic attractors
that cause price to "reject" and return to prior ranges.

Renaissance principles:
- Segment relentlessly: separate long/short detection per HVN level
- Instrument everything: HVN distance and volume rank logged
- Earn the right through proof: proximity + reversal dual gate required
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

# Maximum ATR distance from HVN to qualify as "testing" the level
_HVN_PROXIMITY_ATR = 0.3


@dataclass
class HVNRejectionPlugin:
    """Mean-reversion setup: price approaches HVN with momentum reversal confirmation.

    Gates:
    - nearest_hvn_above or nearest_hvn_below available
    - abs(close - nearest_hvn_level) / atr < 0.3
    - Reversal gate: rsi_div_bullish > 0.3 OR stoch_k < 30 (long at hvn_below)
                     rsi_div_bearish > 0.3 OR stoch_k > 70 (short at hvn_above)

    Direction: long if near hvn_below (rejecting down from above), short if near hvn_above
    If both qualify, pick the closer HVN.
    """

    name: str = "trad_HVNRejection"
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
            cfg.get_sync("threshold.hvn_rejection.proximity_atr", _HVN_PROXIMITY_ATR)
            if cfg
            else _HVN_PROXIMITY_ATR
        )
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

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # ── Close price ───────────────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # ── Check proximity to HVN levels ─────────────────────────────────────
        hvn_above = features.get("nearest_hvn_above")
        hvn_below = features.get("nearest_hvn_below")

        near_hvn_above = False
        near_hvn_below = False
        dist_above = float("inf")
        dist_below = float("inf")

        if hvn_above is not None:
            hvn_above = float(hvn_above)
            dist_above = abs(entry - hvn_above) / atr
            near_hvn_above = dist_above < proximity_atr

        if hvn_below is not None:
            hvn_below = float(hvn_below)
            dist_below = abs(entry - hvn_below) / atr
            near_hvn_below = dist_below < proximity_atr

        if not near_hvn_above and not near_hvn_below:
            return no_signal()

        # ── Momentum reversal gate ────────────────────────────────────────────
        rsi_div_bullish = float(features.get("rsi_div_bullish", 0.0))
        rsi_div_bearish = float(features.get("rsi_div_bearish", 0.0))
        stoch_k = float(features.get("stoch_k_14_3", 50.0))

        # Determine candidate directions
        div_threshold = get_div_threshold()
        stoch_oversold = get_stoch_oversold()
        stoch_overbought = get_stoch_overbought()

        can_long = near_hvn_below and (rsi_div_bullish > div_threshold or stoch_k < stoch_oversold)
        can_short = near_hvn_above and (
            rsi_div_bearish > div_threshold or stoch_k > stoch_overbought
        )

        if not can_long and not can_short:
            return no_signal()

        # ── Pick direction (closer HVN wins if both qualify) ──────────────────
        if can_long and can_short:
            direction = 1 if dist_below <= dist_above else -1
        elif can_long:
            direction = 1
        else:
            direction = -1

        # Pick the active HVN level and check reversal
        if direction == 1:
            hvn_level = hvn_below
            dist_atr = dist_below
            reversal_ok, reversal_strength = check_reversal_gate(features, 1)
            if not reversal_ok:
                return no_signal()
        else:
            hvn_level = hvn_above
            dist_atr = dist_above
            reversal_ok, reversal_strength = check_reversal_gate(features, -1)
            if not reversal_ok:
                return no_signal()

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "hvn_rejection_long" if direction == 1 else "hvn_rejection_short"
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

        # ── Confidence scoring ────────────────────────────────────────────────
        # Proximity to HVN: 0.3 weight
        proximity_score = max(0.0, 1.0 - dist_atr / proximity_atr)

        # Reversal strength: 0.3 weight
        reversal_score = min(1.0, max(0.0, reversal_strength))

        # HVN dist_atr from legacy field: 0.2 weight (closer = stronger)
        legacy_hvn_dist = float(features.get("nearest_hvn_dist_atr") or 1.0)
        hvn_dist_score = max(0.0, 1.0 - legacy_hvn_dist / 2.0)

        # Vol regime stability: 0.2 weight
        vol_regime = float(features.get("vol_regime") or 0.5)
        vol_stability = 1.0 - abs(vol_regime - 0.5) * 2.0

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "proximity_score": round(proximity_score, 4),
            "reversal_score": round(reversal_score, 4),
            "hvn_dist_score": round(hvn_dist_score, 4),
            "vol_stability": round(vol_stability, 4),
        }

        raw_conf = (
            0.30 * proximity_score
            + 0.30 * reversal_score
            + 0.20 * hvn_dist_score
            + 0.20 * vol_stability
        )

        # ── Supporting factors ────────────────────────────────────────────────
        rsi_div_ok = (direction == 1 and rsi_div_bullish > div_threshold) or (
            direction == -1 and rsi_div_bearish > div_threshold
        )
        stoch_ok = (direction == 1 and stoch_k < stoch_oversold) or (
            direction == -1 and stoch_k > stoch_overbought
        )

        supporting: list[str] = [
            f"hvn_level={hvn_level:.2f}",
            f"hvn_distance_entered_atr={dist_atr:.3f}",
            "hvn_volume_rank=0.0",  # placeholder — volume rank not yet computed
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


plugin = HVNRejectionPlugin()
