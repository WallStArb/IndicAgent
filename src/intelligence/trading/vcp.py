"""trad_VCP — Volatility Contraction Pattern breakout evidence-contributor.

Fires on the breakout bar after 3+ successive bars with decreasing H-L range and
declining volume, followed by a volume-expansion breakout bar that closes beyond
the prior bar's range.

Session reset: contraction list clears at the start of each new trading day (ET).

Renaissance principles:
- Segment relentlessly: VCP is definitionally a trend-regime setup; filters ranging markets
- Earn the right through proof: requires >= 3 contractions + HMM prob >= 0.60 before firing
- Instrument everything: contraction_count and session_date captured in every signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from ..plugins import InputSpec
from .trade_framer import frame_trade

_ET_TZ = ZoneInfo("America/New_York")

# Minimum number of contractions before expansion bar can fire
_MIN_CONTRACTIONS = 3

# Volume expansion multiplier: expansion bar must have volume > last contraction × this
_VOL_EXPANSION_MULT = 1.2

# Minimum HMM regime probability
_MIN_HMM_PROB = 0.60


@dataclass
class VCPPlugin:
    """I7 evidence contributor: fires on VCP breakout after 3+ volatility contractions.

    Gate 1: hmm_regime must be 1.0 (bullish) or 2.0 (bearish) with prob >= 0.60.
    Gate 2: 3+ successive bars with decreasing H-L range AND declining volume.
    Gate 3: expansion bar closes beyond prior bar's high/low (directional confirmation).
    Gate 4: expansion bar volume > last contraction volume × 1.2.

    Session reset: contraction list clears on new trading day (ET date change).
    """

    name: str = "trad_VCP"
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
            "contraction_count",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "volatility", "contraction", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
            return {}

        # ── State ───────────────────────────────────────────────────────────
        state = self._state.get((symbol, tf), {})

        # ── Session date reset ───────────────────────────────────────────────
        if "timestamp" in df.columns:
            ts_raw = df["timestamp"].iloc[-1]
            if hasattr(ts_raw, "to_pydatetime"):
                ts_raw = ts_raw.to_pydatetime()
            if isinstance(ts_raw, datetime):
                if ts_raw.tzinfo is None:
                    ts_raw = ts_raw.replace(tzinfo=UTC)
                et = ts_raw.astimezone(_ET_TZ)
                session_date = et.date()
                if session_date != state.get("session_date"):
                    state = {"session_date": session_date, "contractions": []}

        # ── Regime gate ──────────────────────────────────────────────────────
        hmm_regime = float(features.get("hmm_regime", 0.0))
        if hmm_regime not in (1.0, 2.0):
            self._state[(symbol, tf)] = state
            return self._no_signal()

        hmm_regime_prob = float(features.get("hmm_regime_prob", 0.0))
        if hmm_regime_prob < _MIN_HMM_PROB:
            self._state[(symbol, tf)] = state
            return self._no_signal()

        # ── Price and volume arrays ──────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        # ── ATR with fallback ────────────────────────────────────────────────
        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            self._state[(symbol, tf)] = state
            return self._no_signal()

        # ── Current bar metrics ──────────────────────────────────────────────
        bar_range = float(high[-1] - low[-1])
        bar_volume = float(df["volume"].iloc[-1])
        close_price = float(close[-1])
        prior_high = float(high[-2])
        prior_low = float(low[-2])

        # ── Contraction tracking ─────────────────────────────────────────────
        contractions: list[tuple[float, float]] = state.get("contractions", [])

        if len(contractions) == 0:
            # Seed the list with the current bar as the first potential contraction
            contractions.append((bar_range, bar_volume))
            state["contractions"] = contractions
            self._state[(symbol, tf)] = state
            return self._no_signal()

        last_range, last_vol = contractions[-1]

        is_contraction = bar_range < last_range and bar_volume <= last_vol
        is_expansion = bar_range >= last_range

        if is_contraction:
            # Continue the contraction sequence
            contractions.append((bar_range, bar_volume))
            state["contractions"] = contractions
            self._state[(symbol, tf)] = state
            return self._no_signal()

        if is_expansion and len(contractions) >= _MIN_CONTRACTIONS:
            # Potential expansion bar — check all gates

            # Volume expansion gate
            if bar_volume <= last_vol * _VOL_EXPANSION_MULT:
                # Volume not expanding enough — reset
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return self._no_signal()

            # Direction from HMM
            direction = 1 if hmm_regime == 1.0 else -1

            # Breakout confirmation: close must break prior bar's high (long) or low (short)
            if direction == 1 and close_price <= prior_high:
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return self._no_signal()
            if direction == -1 and close_price >= prior_low:
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return self._no_signal()

            contraction_count = len(contractions)
            signal_type = "vcp_breakout_long" if direction == 1 else "vcp_breakout_short"

            # ── Trade frame ────────────────────────────────────────────────
            frame = frame_trade(
                setup_type=signal_type,
                direction=direction,
                entry=close_price,
                features=features,
                atr=atr,
            )
            if not frame.viable:
                # Reset contractions
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return self._no_signal()

            # ── Confidence ─────────────────────────────────────────────────
            confidence = 0.50
            if contraction_count >= 4:
                confidence += 0.08
            if hmm_regime_prob > 0.75:
                confidence += 0.07
            confidence = round(min(0.95, max(0.10, confidence)), 4)

            # ── Regime context ─────────────────────────────────────────────
            regime_ctx = "bullish" if direction == 1 else "bearish"

            supporting = [
                f"contraction_count={contraction_count}",
                f"expansion_range={bar_range:.2f}",
                f"expansion_vol={bar_volume:.0f}",
                f"last_contraction_vol={last_vol:.0f}",
                "volume_expansion_confirmed",
            ]

            # ── Clear contractions after fire ──────────────────────────────
            state["contractions"] = []
            self._state[(symbol, tf)] = state

            return {
                "signal_type": signal_type,
                "direction": direction,
                "entry_price": round(frame.entry, 2),
                "stop_loss": round(frame.stop, 2),
                "targets": [round(t.price, 2) for t in frame.targets],
                "confidence": confidence,
                "regime_context": regime_ctx,
                "supporting_factors": supporting,
                "contraction_count": contraction_count,
            }

        else:
            # Not a contraction, not a valid expansion -> reset
            contractions = [(bar_range, bar_volume)]
            state["contractions"] = contractions
            self._state[(symbol, tf)] = state
            return self._no_signal()

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = VCPPlugin()
