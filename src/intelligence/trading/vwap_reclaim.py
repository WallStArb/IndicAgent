"""trad_VWAPReclaim — I7 any-regime setup for VWAP reclaim/break signals.

Fires when price crosses back through session VWAP after spending bars on
the "wrong" side, with volume expansion confirming the move. Works in any
regime (trend or ranging) as VWAP reclaims/breaks are regime-agnostic.

Renaissance principles:
- Instrument everything: tracks bars_below/bars_above per symbol+tf
- Segment relentlessly: separate state per (symbol, timeframe) key
- Degrade gracefully: ORB15 volume fallback when rel_volume unavailable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .plugin_utils import no_signal
from .trade_framer import frame_trade

# Minimum volume ratio for signal confirmation
_VOL_THRESHOLD: float = 1.2

# Maximum bars to track on wrong side (prevents unbounded memory)
_MAX_BARS_TRACKED: int = 20


@dataclass
class VWAPReclaimPlugin:
    """Any-regime setup: fires on VWAP reclaim (from below) or break (from above).

    Gates:
    - Prior bar must be on opposite side of session_vwap from current bar (cross required)
    - bars_below > 0 (for long reclaim) or bars_above > 0 (for short break) before the cross
    - Volume expansion: rel_volume >= 1.2 (or bar_vol >= 1.2 × session_avg via fallback)

    State: tracks bars_below and bars_above per (symbol, timeframe) key.
    State is updated BEFORE signal check so the counter reflects history accumulated
    before the current crossing bar (bars_below/above includes the current bar only
    after we update; we capture the pre-update value to test "spent N bars on wrong side").
    """

    name: str = "trad_VWAPReclaim"
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
    capability_tags: frozenset[str] = frozenset({"trading", "any"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        timeframe = frames.get("timeframe", "")
        if timeframe and timeframe not in ("1m", "5m", "15m"):
            return no_signal()

        df = frames.get("main")
        features = frames.get("features") or {}
        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Required: session_vwap ────────────────────────────────────────────
        session_vwap = features.get("session_vwap")
        if session_vwap is None:
            return no_signal()
        session_vwap = float(session_vwap)

        # ── Current position relative to VWAP ────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        above_now = current_close > session_vwap

        # ── Load prior state (before this bar) ───────────────────────────────
        key = (symbol, tf)
        state = self._state.get(key, {})
        above_prev = state.get("above_vwap_prev", None)
        bars_below = state.get("bars_below", 0)
        bars_above = state.get("bars_above", 0)

        # Capture pre-update counts: these reflect history BEFORE the current bar
        pre_bars_below = bars_below
        pre_bars_above = bars_above

        # ── Update counters for the current bar ───────────────────────────────
        if above_now:
            bars_above = min(bars_above + 1, _MAX_BARS_TRACKED)
            bars_below = 0
        else:
            bars_below = min(bars_below + 1, _MAX_BARS_TRACKED)
            bars_above = 0

        state["above_vwap_prev"] = above_now
        state["bars_below"] = bars_below
        state["bars_above"] = bars_above
        self._state[key] = state

        # ── Require prior state to detect a cross ─────────────────────────────
        if above_prev is None:
            return no_signal()

        # ── Detect cross ──────────────────────────────────────────────────────
        crossed_up = (not above_prev) and above_now    # was below → now above (long reclaim)
        crossed_down = above_prev and (not above_now)  # was above → now below (short break)

        if not (crossed_up or crossed_down):
            return no_signal()

        # ── Validate "spent time on wrong side" before the cross ─────────────
        if crossed_up and pre_bars_below == 0:
            # Never actually spent time below VWAP before reclaiming
            return no_signal()
        if crossed_down and pre_bars_above == 0:
            # Never spent time above VWAP before breaking down
            return no_signal()

        direction = 1 if crossed_up else -1
        bars_wrong_side = pre_bars_below if crossed_up else pre_bars_above

        # ── Volume gate ───────────────────────────────────────────────────────
        rel_volume = features.get("rel_volume")
        if rel_volume is not None and isinstance(rel_volume, (int, float)):
            vol_ok = float(rel_volume) >= _VOL_THRESHOLD
            volume_ratio = float(rel_volume)
        else:
            bar_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].mean())
            vol_ok = avg_vol > 0 and bar_vol >= _VOL_THRESHOLD * avg_vol
            volume_ratio = (bar_vol / avg_vol) if avg_vol > 0 else 0.0

        if not vol_ok:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        # ── Entry ─────────────────────────────────────────────────────────────
        entry = float(close[-1])

        # ── Trade frame ───────────────────────────────────────────────────────
        signal_type = "vwap_reclaim_long" if direction == 1 else "vwap_reclaim_short"
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            return no_signal()

        # ── Confidence scoring ────────────────────────────────────────────────
        # Volume ratio: 0.3 weight
        vol_score = min(1.0, max(0.0, (volume_ratio - _VOL_THRESHOLD) / _VOL_THRESHOLD))

        # bars_wrong_side duration: 0.3 weight (capped at 10 bars for scoring)
        duration_score = min(1.0, bars_wrong_side / 10.0)

        # Trend regime alignment: 0.2 weight
        hmm = float(features.get("hmm_regime", 0.0))
        if (direction == 1 and hmm == 1.0) or (direction == -1 and hmm == 2.0):
            trend_align = 0.8
        elif hmm == 0.0:
            trend_align = 0.5
        else:
            trend_align = 0.3

        # S/R proximity: 0.2 weight
        if direction == 1:
            sr = float(features.get("sr_nearest_support", 0.0)) or float(
                features.get("nearest_support", 0.0)
            )
        else:
            sr = float(features.get("sr_nearest_resistance", 0.0)) or float(
                features.get("nearest_resistance", 0.0)
            )
        sr_prox = max(0.0, 1.0 - abs(entry - sr) / (atr * 3.0)) if sr > 0 and atr > 0 else 0.0

        raw_conf = (
            0.30 * vol_score
            + 0.30 * duration_score
            + 0.20 * trend_align
            + 0.20 * sr_prox
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # ── Supporting factors ────────────────────────────────────────────────
        side_label = "bars_below_vwap" if direction == 1 else "bars_above_vwap"
        supporting: list[str] = [
            f"{side_label}={bars_wrong_side}",
            f"vwap_reclaim_volume_ratio={volume_ratio:.2f}",
        ]
        if trend_align > 0.6:
            supporting.append("trend_regime_aligned")

        regime_ctx = "bullish" if direction == 1 else "bearish"
        if hmm == 0.0:
            regime_ctx = "ranging"

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


plugin = VWAPReclaimPlugin()
