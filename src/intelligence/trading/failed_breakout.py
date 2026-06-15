"""trad_FailedBreakout — BOS reversal evidence-contributor.

Gates on bos_detected==1.0 (SMC BOS plugin output). Tracks bars_since_bos in
_state. Fires when price closes back through the BOS level within a 3-bar window,
confirming the breakout failed and a reversal is underway.

High conviction in mean-reversion regimes (hmm_regime==0.0), penalised in trend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
    rel_volume_score,
)
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

# Maximum bars after BOS detection to wait for close-back-through reversal
_MAX_REVERSAL_BARS: int = 3


@dataclass
class FailedBreakoutPlugin:
    """I7 evidence contributor: fires when a BOS fails and price reverses within 3 bars.

    Gate: bos_detected == 1.0 (stores state), then close[-1] crosses back through
    bos_level on a subsequent bar within _MAX_REVERSAL_BARS.

    Confidence: 4-factor intrinsic composite via compose_confidence().
    """

    name: str = "trad_FailedBreakout"
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
    capability_tags: frozenset[str] = frozenset({"trading", "reversal", "structure", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
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
        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
            return {}

        state = self._state.get((symbol, tf), {})

        # ── Check for new BOS event ──────────────────────────────────────────
        bos_detected = float(features.get("bos_detected", 0.0))
        if bos_detected == 1.0:
            bos_level = float(features.get("bos_level", 0.0))
            bos_direction = int(features.get("bos_direction", 0))
            if bos_level > 0:
                # Start fresh tracking (overwrite any prior in-progress BOS)
                state = {
                    "bos_level": bos_level,
                    "bos_direction": bos_direction,
                    "bars_since_bos": 0,
                }
                self._state[(symbol, tf)] = state
                # On the bar that detects BOS, check immediately for reversal
                # (in case the reversal happens on the same bar — rare, but correct)
        else:
            # Increment staleness counter if tracking an active BOS
            if state.get("bos_level"):
                state["bars_since_bos"] = state.get("bars_since_bos", 0) + 1

        # ── Gate: no active BOS tracking ────────────────────────────────────
        if not state.get("bos_level"):
            self._state[(symbol, tf)] = state
            return no_signal()

        bos_level = float(state["bos_level"])
        bos_direction = int(state["bos_direction"])
        bars_since_bos = int(state.get("bars_since_bos", 0))

        # ── Gate: reversal window expired ────────────────────────────────────
        if bars_since_bos > _MAX_REVERSAL_BARS:
            # Clear BOS tracking — window missed
            state.clear()
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Dual gate (before OHLCV numeric access) ──────────────────────────
        # Gate 1: direction-specific trend form — block only if BOTH up AND down are below threshold
        if hmm_trending_weight(features) < get_min_regime_weight():
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Reversal check ───────────────────────────────────────────────────
        close_price = float(df["close"].iloc[-1])

        if bos_direction == -1:
            # Bearish BOS (price broke below structure). Reversal = close back ABOVE bos_level
            reversal = close_price > bos_level
            direction = 1  # Long — failed bearish breakout
            signal_type = "failed_breakout_long"
        elif bos_direction == 1:
            # Bullish BOS (price broke above structure). Reversal = close back BELOW bos_level
            reversal = close_price < bos_level
            direction = -1  # Short — failed bullish breakout
            signal_type = "failed_breakout_short"
        else:
            # Unknown direction — cannot determine reversal
            self._state[(symbol, tf)] = state
            return no_signal()

        if not reversal:
            self._state[(symbol, tf)] = state
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            self._state[(symbol, tf)] = state
            return no_signal()

        reversal_close_delta = abs(close_price - bos_level)
        entry = close_price

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        # break_magnitude_score: how far price crossed back through BOS (reversal strength)
        break_magnitude_score = clamp01(reversal_close_delta / max(1e-9, atr))

        # rejection_strength_score: sooner reversal = stronger rejection (bars_since_bos=0 is best)
        rejection_strength_score = clamp01(
            (_MAX_REVERSAL_BARS - bars_since_bos) / _MAX_REVERSAL_BARS
        )

        # volume_score: rel_volume confirmation
        volume_score = rel_volume_score(features)

        # structure_quality_score: BOS level quality (bos_confidence from SMC if available)
        bos_confidence = features.get("bos_confidence")
        if bos_confidence is not None:
            structure_quality_score = clamp01(float(bos_confidence))
        else:
            structure_quality_score = 0.5  # neutral fallback

        # Weights sum to 1.0
        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "break_magnitude_score": round(break_magnitude_score, 4),
            "rejection_strength_score": round(rejection_strength_score, 4),
            "volume_score": round(volume_score, 4),
            "structure_quality_score": round(structure_quality_score, 4),
        }

        raw_conf = (
            0.35 * break_magnitude_score
            + 0.30 * rejection_strength_score
            + 0.20 * volume_score
            + 0.15 * structure_quality_score
        )
        confidence = compose_confidence(raw_conf)

        # ── Trade frame ─────────────────────────────────────────────────────
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )
        if not frame.viable:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Signal fired — clear BOS tracking ────────────────────────────────
        state.clear()
        self._state[(symbol, tf)] = state

        hmm_regime = float(features.get("hmm_regime", 0.0))
        if hmm_regime == 0.0:
            regime_ctx = "ranging"
        elif hmm_regime in (1.0, 2.0):
            regime_ctx = "bearish" if hmm_regime == 2.0 else "bullish"
        else:
            regime_ctx = "neutral"

        supporting = [
            f"bos_level={bos_level:.2f}",
            f"bars_since_bos={bars_since_bos}",
            f"reversal_close_delta={reversal_close_delta:.4f}",
            "bos_reversal_confirmed",
        ]
        if hmm_regime == 0.0:
            supporting.append("hmm_ranging_aligned")

        signal = make_signal_from_frame(
            frame,
            symbol=symbol,
            timeframe=tf,
            timestamp="",
            signal_type=signal_type,
            setup_plugin="trad_FailedBreakout",
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FailedBreakoutPlugin()
