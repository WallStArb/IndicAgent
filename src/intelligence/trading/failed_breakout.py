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
from .atr_utils import get_atr
from .confidence_utils import compose_confidence
from .plugin_utils import no_signal
from .trade_framer import frame_trade

# Maximum bars after BOS detection to wait for close-back-through reversal
_MAX_REVERSAL_BARS: int = 3


@dataclass
class FailedBreakoutPlugin:
    """I7 evidence contributor: fires when a BOS fails and price reverses within 3 bars.

    Gate: bos_detected == 1.0 (stores state), then close[-1] crosses back through
    bos_level on a subsequent bar within _MAX_REVERSAL_BARS.

    Confidence: 0.55 base + 0.15 if ranging (mean_reversion aligned) - 0.10 if trend.
    """

    name: str = "trad_FailedBreakout"
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        atr = get_atr(features)
        if atr is None:
            return no_signal()

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

        # ── Reversal check ───────────────────────────────────────────────────
        close_price = float(close[-1])
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

        # ── Confidence ──────────────────────────────────────────────────────
        hmm_regime = float(features.get("hmm_regime", 0.0))
        confidence = 0.55
        if hmm_regime == 0.0:
            # Ranging regime — mean-reversion aligned
            confidence += 0.15
            regime_ctx = "ranging"
        elif hmm_regime in (1.0, 2.0):
            # Trending regime — less aligned with reversal
            confidence -= 0.10
            regime_ctx = "bearish" if hmm_regime == 2.0 else "bullish"
        else:
            regime_ctx = "neutral"

        confidence = compose_confidence(confidence)

        reversal_close_delta = abs(close_price - bos_level)

        entry = close_price

        # ── Trade frame ─────────────────────────────────────────────────────
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Signal fired — clear BOS tracking ────────────────────────────────
        state.clear()
        self._state[(symbol, tf)] = state

        supporting = [
            f"bos_level={bos_level:.2f}",
            f"bars_since_bos={bars_since_bos}",
            f"reversal_close_delta={reversal_close_delta:.4f}",
            "bos_reversal_confirmed",
        ]
        if hmm_regime == 0.0:
            supporting.append("hmm_ranging_aligned")

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(frame.entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": [round(t.price, 2) for t in frame.targets],
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FailedBreakoutPlugin()
