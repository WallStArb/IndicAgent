"""trad_ORB30 — Opening Range Breakout (30-min window) evidence-contributor.

Accumulates the high/low of bars from 09:30-10:00 ET to define the opening range.
Fires on the first breakout bar (close beyond the range) with volume expansion
(>1.5× session average) after 10:00 ET, within a 09:30-11:30 ET session gate.

Identical logic to ORB15 except the accumulation window is 09:30-10:00 ET.
Implemented as a separate class (not a shared base) for independent statistical
tracking and clear plugin registration.

VERDICT: CORRECT-RARE (Phase 126 audit)
  Gate logic is correct. Fires at most twice per RTH session per symbol (once long,
  once short) via fire-once guard. Accumulation window is 09:30-09:59 ET; breakout
  window is 10:00-11:30 ET. Zero fires in corpus is expected for the same reasons as
  ORB15: RTH session coverage, volume expansion gate stringency, and pipeline availability
  during US market hours.
  VERIFIED: range accumulation logic (09:30-09:59 ET), breakout detection (close > orb_high
  or close < orb_low), fire-once guard, and volume gate are all structurally correct.
  No code change required.

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
from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
)
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
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
    capability_tags: frozenset[str] = frozenset({"trading", "session", "breakout", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        vol_expansion_threshold = (
            cfg.get_sync("threshold.orb.vol_expansion_mult", _VOL_EXPANSION_THRESHOLD)
            if cfg
            else _VOL_EXPANSION_THRESHOLD
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
        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Gate 1: continuous trending regime ────────────────────────────────
        if hmm_trending_weight(features) < get_min_regime_weight():
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
        atr = get_atr_with_floor_from_frames(frames)
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
            volume_ratio = float(rel_volume)
            vol_ok = volume_ratio >= vol_expansion_threshold
        else:
            bar_volume = float(df["volume"].iloc[-1])
            avg_volume = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else 0.0
            vol_ok = avg_volume > 0 and bar_volume >= vol_expansion_threshold * avg_volume
            volume_ratio = (bar_volume / avg_volume) if avg_volume > 0 else 0.0

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

        # ── Gap bias (gap_alignment_score factor) ─────────────────────────────
        gap_alignment_score = 0.5  # neutral default
        pdc = features.get("prior_session_close")
        if pdc is not None and isinstance(pdc, (int, float)) and float(pdc) > 0:
            open_price = state.get("session_open") or float(df["open"].iloc[0])
            gap_pct = (open_price - float(pdc)) / float(pdc)
            if abs(gap_pct) > 0.001:
                if (direction == 1 and gap_pct > 0) or (direction == -1 and gap_pct < 0):
                    gap_alignment_score = 0.80  # gap aligns with breakout direction
                else:
                    gap_alignment_score = 0.20  # gap misaligns

        # ── 4-factor confidence composite (NO HMM probability) ───────────────
        range_width = abs(orb_high - orb_low)

        # Breakout margin vs ATR: how far beyond range did price close?
        breakout_excess = abs(close_price - (orb_high if direction == 1 else orb_low))
        breakout_margin_score = clamp01(breakout_excess / atr) if atr > 0 else 0.5

        # Range quality: tighter opening range (relative to ATR) = cleaner setup
        range_quality_score = clamp01(1.0 - range_width / (atr * 2.0)) if atr > 0 else 0.5

        # Volume score: rel_volume expansion above threshold
        volume_score = clamp01((volume_ratio - vol_expansion_threshold) / vol_expansion_threshold)

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "breakout_margin_score": round(breakout_margin_score, 4),
            "range_quality_score": round(range_quality_score, 4),
            "volume_score": round(volume_score, 4),
            "gap_alignment_score": round(gap_alignment_score, 4),
        }

        # Weights: 0.35 + 0.25 + 0.25 + 0.15 = 1.0
        raw_conf = (
            0.35 * breakout_margin_score
            + 0.25 * range_quality_score
            + 0.25 * volume_score
            + 0.15 * gap_alignment_score
        )

        regime_ctx = "bullish" if direction == 1 else "bearish"

        # ── Trade frame ──────────────────────────────────────────────────────
        frame = frame_trade(
            setup_type=signal_type,
            direction=direction,
            entry=close_price,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
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
            f"breakout_margin_score={breakout_margin_score:.3f}",
        ]
        if abs(gap_alignment_score - 0.5) > 0.1:
            supporting.append(
                f"gap_alignment={'aligned' if gap_alignment_score > 0.5 else 'misaligned'}"
            )

        confidence = compose_confidence(raw_conf)

        signal = make_signal_from_frame(
            frame,
            symbol=symbol,
            timeframe=timeframe,
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


plugin = ORB30Plugin()
