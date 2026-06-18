"""trad_PrevDayLevelTest — Previous Day Level Test evidence-contributor.

Fires fade and continuation setups near PDH / PDL / PDC (Previous Day High / Low / Close).

Fade variant: price approaches the level with reversal momentum (bearish at PDH, bullish at PDL).
Continuation variant: price broke through a level and is now pulling back to re-test it.

Both variants call trade_framer.py for structural stop/target resolution.

Renaissance principles:
- Segment relentlessly: two distinct variants (fade vs continuation) with regime-specific confidence
- Earn the right through proof: proximity gate (0.5×ATR) prevents noise trades
- Instrument everything: level_name, level_value, setup_variant captured in every signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import compose_confidence
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_ET_TZ = ZoneInfo("America/New_York")


@dataclass
class PrevDayLevelTestPlugin:
    """I7 evidence contributor: fade and continuation setups near PDH/PDL/PDC.

    Gate: close within 0.5×ATR of any prior-session level.
    Fade direction: inferred from bar momentum (bearish at PDH = short; bullish at PDL = long).
    Continuation: tracked via _state after a clean breakout above/below the level.
    Confidence boosted by regime alignment (ranging favours fade, trending favours continuation).
    """

    name: str = "trad_PrevDayLevelTest"
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
            "setup_variant",
            "level_name",
            "level_value",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "level_test", "session", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
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
            return {}

        # ── Extract price arrays ────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

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
                session_date = ts_raw.astimezone(_ET_TZ).date()
                if session_date != state.get("session_date"):
                    state = {"session_date": session_date}

        # ── Prior session levels ─────────────────────────────────────────────
        pdh_raw = features.get("prior_session_high")
        pdl_raw = features.get("prior_session_low")
        pdc_raw = features.get("prior_session_close")

        def _valid_level(v: Any) -> bool:
            return isinstance(v, (int, float)) and float(v) > 0

        if not (_valid_level(pdh_raw) or _valid_level(pdl_raw) or _valid_level(pdc_raw)):
            self._state[(symbol, tf)] = state
            return no_signal()

        pdh = float(pdh_raw) if _valid_level(pdh_raw) else None
        pdl = float(pdl_raw) if _valid_level(pdl_raw) else None
        pdc = float(pdc_raw) if _valid_level(pdc_raw) else None

        close_price = float(close[-1])
        open_price = float(df["open"].iloc[-1])

        # ── Breakout tracking for continuation ──────────────────────────────
        # If close is clearly outside a level (beyond proximity zone) -> mark breakout
        proximity = 0.5 * atr
        if pdh is not None and close_price > pdh + proximity:
            state["breakout_level"] = pdh
            state["breakout_direction"] = 1
        elif pdl is not None and close_price < pdl - proximity:
            state["breakout_level"] = pdl
            state["breakout_direction"] = -1

        # ── Proximity check for each level ──────────────────────────────────
        near_pdh = pdh is not None and abs(close_price - pdh) < proximity
        near_pdl = pdl is not None and abs(close_price - pdl) < proximity
        near_pdc = pdc is not None and abs(close_price - pdc) < proximity

        if not (near_pdh or near_pdl or near_pdc):
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Pick nearest level ───────────────────────────────────────────────
        candidates: list[tuple[float, str, float]] = []
        if near_pdh and pdh is not None:
            candidates.append((abs(close_price - pdh), "PDH", pdh))
        if near_pdl and pdl is not None:
            candidates.append((abs(close_price - pdl), "PDL", pdl))
        if near_pdc and pdc is not None:
            candidates.append((abs(close_price - pdc), "PDC", pdc))

        candidates.sort(key=lambda x: x[0])
        _, level_name, level_value = candidates[0]

        # ── Variant detection ────────────────────────────────────────────────
        breakout_level = state.get("breakout_level")
        breakout_direction = state.get("breakout_direction", 0)

        is_continuation = (
            breakout_level is not None
            and abs(breakout_level - level_value) < 1e-6
            and (
                (breakout_direction == 1 and close_price >= level_value)
                or (breakout_direction == -1 and close_price <= level_value)
            )
        )

        if is_continuation:
            setup_variant = "continuation"
            direction = breakout_direction
            if direction == 1:
                signal_type = "prev_day_cont_long"
            else:
                signal_type = "prev_day_cont_short"
        else:
            setup_variant = "fade"
            if level_name == "PDH":
                direction = -1
                signal_type = "prev_day_fade_short"
            elif level_name == "PDL":
                direction = 1
                signal_type = "prev_day_fade_long"
            else:
                # PDC: infer from bar direction
                if close_price < open_price:
                    direction = -1
                    signal_type = "prev_day_fade_short"
                else:
                    direction = 1
                    signal_type = "prev_day_fade_long"

        # ── Confidence ───────────────────────────────────────────────────────
        hmm_regime = float(features.get("hmm_regime", 0.0))
        confidence = 0.50

        # ── Regime context ───────────────────────────────────────────────────
        if hmm_regime == 1.0:
            regime_ctx = "bullish"
        elif hmm_regime == 2.0:
            regime_ctx = "bearish"
        else:
            regime_ctx = "ranging"

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

        # ── Write state back ─────────────────────────────────────────────────
        self._state[(symbol, tf)] = state

        supporting = [
            f"{level_name}={level_value:.2f}",
            f"close={close_price:.2f}",
            f"proximity={proximity:.2f}",
            f"setup_variant={setup_variant}",
        ]

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "proximity_score": round(max(0.0, 1.0 - abs(close_price - level_value) / proximity), 4),
            "continuation_score": round(1.0 if is_continuation else 0.0, 4),
        }

        confidence = compose_confidence(confidence)

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
        signal["setup_variant"] = setup_variant
        signal["level_name"] = level_name
        signal["level_value"] = level_value
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = PrevDayLevelTestPlugin()
