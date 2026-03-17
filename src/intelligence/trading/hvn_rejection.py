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

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .trade_framer import frame_trade

# Maximum ATR distance from HVN to qualify as "testing" the level
_HVN_PROXIMITY_ATR = 0.3

# Minimum divergence confidence to count as reversal
_DIV_THRESHOLD = 0.3

# Stochastic thresholds
_STOCH_OVERSOLD = 30.0
_STOCH_OVERBOUGHT = 70.0


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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "mean_reversion"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        # ── ATR ───────────────────────────────────────────────────────────────
        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

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
            near_hvn_above = dist_above < _HVN_PROXIMITY_ATR

        if hvn_below is not None:
            hvn_below = float(hvn_below)
            dist_below = abs(entry - hvn_below) / atr
            near_hvn_below = dist_below < _HVN_PROXIMITY_ATR

        if not near_hvn_above and not near_hvn_below:
            return self._no_signal()

        # ── Momentum reversal gate ────────────────────────────────────────────
        rsi_div_bullish = float(features.get("rsi_div_bullish", 0.0))
        rsi_div_bearish = float(features.get("rsi_div_bearish", 0.0))
        stoch_k = float(features.get("stoch_k_14_3", 50.0))

        # Determine candidate directions
        can_long = near_hvn_below and (
            rsi_div_bullish > _DIV_THRESHOLD or stoch_k < _STOCH_OVERSOLD
        )
        can_short = near_hvn_above and (
            rsi_div_bearish > _DIV_THRESHOLD or stoch_k > _STOCH_OVERBOUGHT
        )

        if not can_long and not can_short:
            return self._no_signal()

        # ── Pick direction (closer HVN wins if both qualify) ──────────────────
        if can_long and can_short:
            direction = 1 if dist_below <= dist_above else -1
        elif can_long:
            direction = 1
        else:
            direction = -1

        # Pick the active HVN level
        if direction == 1:
            hvn_level = hvn_below
            dist_atr = dist_below
            reversal_strength = max(
                rsi_div_bullish,
                (30.0 - stoch_k) / 30.0 if stoch_k < _STOCH_OVERSOLD else 0.0,
            )
        else:
            hvn_level = hvn_above
            dist_atr = dist_above
            reversal_strength = max(
                rsi_div_bearish,
                (stoch_k - 70.0) / 30.0 if stoch_k > _STOCH_OVERBOUGHT else 0.0,
            )

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "hvn_rejection_long" if direction == 1 else "hvn_rejection_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            return self._no_signal()

        # ── Confidence scoring ────────────────────────────────────────────────
        # Proximity to HVN: 0.3 weight
        proximity_score = max(0.0, 1.0 - dist_atr / _HVN_PROXIMITY_ATR)

        # Reversal strength: 0.3 weight
        reversal_score = min(1.0, max(0.0, reversal_strength))

        # HVN dist_atr from legacy field: 0.2 weight (closer = stronger)
        legacy_hvn_dist = float(features.get("nearest_hvn_dist_atr", 1.0))
        hvn_dist_score = max(0.0, 1.0 - legacy_hvn_dist / 2.0)

        # Vol regime stability: 0.2 weight
        vol_regime = float(features.get("vol_regime", 0.5))
        vol_stability = 1.0 - abs(vol_regime - 0.5) * 2.0

        raw_conf = (
            0.30 * proximity_score
            + 0.30 * reversal_score
            + 0.20 * hvn_dist_score
            + 0.20 * vol_stability
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # ── Supporting factors ────────────────────────────────────────────────
        supporting: list[str] = [
            f"hvn_level={hvn_level:.2f}",
            f"hvn_distance_entered_atr={dist_atr:.3f}",
            "hvn_volume_rank=0.0",  # placeholder — volume rank not yet computed
        ]
        if direction == 1 and rsi_div_bullish > _DIV_THRESHOLD:
            supporting.append("rsi_div_bullish")
        elif direction == -1 and rsi_div_bearish > _DIV_THRESHOLD:
            supporting.append("rsi_div_bearish")
        if (direction == 1 and stoch_k < _STOCH_OVERSOLD) or (
            direction == -1 and stoch_k > _STOCH_OVERBOUGHT
        ):
            supporting.append(f"stoch_extreme={stoch_k:.1f}")

        hmm = float(features.get("hmm_regime", 0.0))
        regime_ctx = "ranging" if hmm == 0 else ("trending_up" if hmm == 1 else "trending_down")

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": [round(t.price, 2) for t in frame.targets],
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = HVNRejectionPlugin()
