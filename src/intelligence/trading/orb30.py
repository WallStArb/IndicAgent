"""trad_ORB30 — Opening Range Breakout (30-min window) evidence-contributor.

Accumulates the high/low of bars from 09:30-10:00 ET to define the opening range.
Fires on the first breakout bar (close beyond the range) with volume expansion
(>1.5× session average) after 10:00 ET, within a 09:30-11:30 ET session gate.

Identical logic to ORB15 except the accumulation window is 09:30-10:00 ET.
Implemented as a separate class (not a shared base) for independent statistical
tracking and clear plugin registration.

Renaissance principles:
- Segment relentlessly: 30-min ORB is a statistically distinct setup from 15-min
- Earn the right through proof: fire-once per direction per session
- Instrument everything: gap bias and regime context in every signal
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .trade_framer import frame_trade

_ET_TZ = ZoneInfo("America/New_York")

# Session gate: only fire signals within this ET window
_SESSION_START = (9, 30)
_SESSION_END = (11, 30)

# Range accumulation window for ORB30: 09:30-10:00 ET
_RANGE_START = (9, 30)
_RANGE_END = (10, 0)

# Volume expansion threshold
_VOL_EXPANSION_THRESHOLD: float = 1.5


def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    """Return True if et_dt wall-clock time is within [start, end)."""
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


@dataclass
class ORB30Plugin:
    """I7 evidence contributor: fires on first post-10:00 breakout beyond the 30-min opening range.

    Range: max(high) / min(low) over 09:30-09:59 ET bars.
    Fire gate: close > orb_high (long) or close < orb_low (short), with volume >1.5× avg.
    Fire-once per direction per session.
    Session gate: 09:30-11:30 ET.
    """

    name: str = "trad_ORB30"
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
    capability_tags: frozenset[str] = frozenset({"trading", "session", "breakout", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
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

        # ── Extract timestamp ────────────────────────────────────────────────
        if "timestamp" not in df.columns:
            return no_signal()
        ts_raw = df["timestamp"].iloc[-1]
        if hasattr(ts_raw, "to_pydatetime"):
            ts_raw = ts_raw.to_pydatetime()
        if not isinstance(ts_raw, datetime):
            return no_signal()
        if ts_raw.tzinfo is None:
            ts_raw = ts_raw.replace(tzinfo=UTC)
        et = ts_raw.astimezone(_ET_TZ)

        state = self._state.get((symbol, tf), {})

        # ── Session date reset ───────────────────────────────────────────────
        if et.date() != state.get("session_date"):
            state = {"session_date": et.date()}
            self._state[(symbol, tf)] = state

        # ── Session gate: 09:30-11:30 ET ────────────────────────────────────
        if not _in_window(et, _SESSION_START, _SESSION_END):
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Range accumulation: 09:30-09:59 ET ──────────────────────────────
        if _in_window(et, _RANGE_START, _RANGE_END) and not state.get("range_complete"):
            bar_high = float(df["high"].iloc[-1])
            bar_low = float(df["low"].iloc[-1])
            if "session_open" not in state:
                state["session_open"] = float(df["open"].iloc[-1])
            state["orb_high"] = max(state.get("orb_high", -math.inf), bar_high)
            state["orb_low"] = min(state.get("orb_low", math.inf), bar_low)
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Mark range complete once past accumulation window ─────────────────
        if not state.get("range_complete"):
            orb_high_accum = state.get("orb_high")
            orb_low_accum = state.get("orb_low")
            if (
                orb_high_accum is None
                or orb_low_accum is None
                or orb_high_accum == -math.inf
                or orb_low_accum == math.inf
            ):
                self._state[(symbol, tf)] = state
                return no_signal()
            state["range_complete"] = True

        orb_high = state.get("orb_high")
        orb_low = state.get("orb_low")
        if orb_high is None or orb_low is None:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── ATR ─────────────────────────────────────────────────────────────
        atr = get_atr(features)
        if atr is None:
            self._state[(symbol, tf)] = state
            return no_signal()

        close_price = float(df["close"].iloc[-1])

        # ── Breakout detection ───────────────────────────────────────────────
        if close_price > orb_high:
            direction = 1
            signal_type = "orb30_breakout_long"
        elif close_price < orb_low:
            direction = -1
            signal_type = "orb30_breakout_short"
        else:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Volume gate ──────────────────────────────────────────────────────
        rel_volume = features.get("rel_volume")
        if rel_volume is not None and isinstance(rel_volume, (int, float)):
            vol_ok = float(rel_volume) >= _VOL_EXPANSION_THRESHOLD
        else:
            bar_volume = float(df["volume"].iloc[-1])
            avg_volume = float(df["volume"].mean())
            vol_ok = avg_volume > 0 and bar_volume >= _VOL_EXPANSION_THRESHOLD * avg_volume

        if not vol_ok:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Fire-once gate ────────────────────────────────────────────────────
        if direction == 1 and state.get("fired_long"):
            self._state[(symbol, tf)] = state
            return no_signal()
        if direction == -1 and state.get("fired_short"):
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Gap bias ─────────────────────────────────────────────────────────
        gap_boost = 0.0
        pdc = features.get("prior_session_close")
        if pdc is not None and isinstance(pdc, (int, float)) and float(pdc) > 0:
            open_price = state.get("session_open") or float(df["open"].iloc[0])
            gap_pct = (open_price - float(pdc)) / float(pdc)
            if abs(gap_pct) > 0.001:
                if (direction == 1 and gap_pct > 0) or (direction == -1 and gap_pct < 0):
                    gap_boost = 0.10
                else:
                    gap_boost = -0.05

        # ── Confidence ───────────────────────────────────────────────────────
        hmm_regime = float(features.get("hmm_regime", 0.0))
        confidence = 0.50
        if hmm_regime in (1.0, 2.0):
            confidence += 0.10
        confidence += gap_boost

        regime_ctx = "bullish" if direction == 1 else "bearish"
        if hmm_regime == 0.0:
            regime_ctx = "ranging"

        # ── Trade frame ──────────────────────────────────────────────────────
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=close_price,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Mark fired ───────────────────────────────────────────────────────
        if direction == 1:
            state["fired_long"] = True
        else:
            state["fired_short"] = True
        self._state[(symbol, tf)] = state

        supporting = [
            f"orb_high={orb_high:.2f}",
            f"orb_low={orb_low:.2f}",
            f"close={close_price:.2f}",
            "volume_expansion_confirmed",
        ]
        if abs(gap_boost) > 0:
            supporting.append(f"gap_bias={gap_boost:+.2f}")

        confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
        confidence = compose_confidence(confidence)

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(frame.entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": [round(t.price, 2) for t in frame.targets],
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "session", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ORB30Plugin()
