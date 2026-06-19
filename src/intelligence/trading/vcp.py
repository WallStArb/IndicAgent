"""trad_VCP — Volatility Contraction Pattern breakout evidence-contributor.

Fires on the breakout bar after 3+ successive bars with decreasing H-L range and
declining volume, followed by a volume-expansion breakout bar that closes beyond
the prior bar's range.

Session reset: contraction list clears at the start of each new trading day (ET).

Renaissance principles:
- Segment relentlessly: VCP is definitionally a trend-regime setup; filters ranging markets
- Earn the right through proof: requires >= 3 contractions + continuous HMM trending gate
- Instrument everything: contraction_count and session_date captured in every signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
)
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_ET_TZ = ZoneInfo("America/New_York")

# Minimum number of contractions before expansion bar can fire
_MIN_CONTRACTIONS = 3

# Volume expansion multiplier: expansion bar must have volume > last contraction × this
_VOL_EXPANSION_MULT = 1.2


@dataclass
class VCPPlugin:
    """I7 evidence contributor: fires on VCP breakout after 3+ volatility contractions.

    Gate 1: hmm_regime_weight (up or down) >= 0.30 — continuous trending gate.
    Gate 2: abs(ctf_score) >= 0.25 — I6 confluence gate (placed before OHLCV access).
    Gate 3: 3+ successive bars with decreasing H-L range AND declining volume.
    Gate 4: expansion bar closes beyond prior bar's high/low (directional confirmation).
    Gate 5: expansion bar volume > last contraction volume × 1.2.

    Direction: from dominant HMM trend direction (up_weight vs down_weight).
    Session reset: contraction list clears on new trading day (ET date change).
    """

    name: str = "trad_VCP"
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
            "contraction_count",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "volatility", "contraction", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

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
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
        cfg = self._config_service
        min_contractions = (
            cfg.get_sync("threshold.vcp.min_contractions", _MIN_CONTRACTIONS)
            if cfg
            else _MIN_CONTRACTIONS
        )
        vol_expansion_mult = (
            cfg.get_sync("threshold.vcp.vol_expansion_mult", _VOL_EXPANSION_MULT)
            if cfg
            else _VOL_EXPANSION_MULT
        )

        symbol = frames.get("__symbol__", "")
        tf = frames.get("__timeframe__", "")

        if df is None or len(df) < self.min_lookback:
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
                et = ts_raw.astimezone(_ET_TZ)
                session_date = et.date()
                if session_date != state.get("session_date"):
                    state = {"session_date": session_date, "contractions": []}

        # ── Gate 1: continuous trending regime ────────────────────────────────
        regime_up = hmm_regime_weight(features, "up")
        regime_down = hmm_regime_weight(features, "down")
        if regime_up < get_min_regime_weight() and regime_down < get_min_regime_weight():
            self._state[(symbol, tf)] = state
            return no_signal()

        # ── Price and volume arrays ──────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            self._state[(symbol, tf)] = state
            return no_signal()

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
            return no_signal()

        last_range, last_vol = contractions[-1]

        is_contraction = bar_range < last_range and bar_volume <= last_vol
        is_expansion = bar_range > last_range

        if is_contraction:
            # Continue the contraction sequence
            contractions.append((bar_range, bar_volume))
            state["contractions"] = contractions
            self._state[(symbol, tf)] = state
            return no_signal()

        if is_expansion and len(contractions) >= min_contractions:
            # Potential expansion bar — check all gates

            # Volume expansion gate
            if bar_volume <= last_vol * vol_expansion_mult:
                # Volume not expanding enough — reset
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return no_signal()

            # Direction: from dominant HMM trend direction (HMM used for DIRECTION only, not confidence)
            direction = 1 if regime_up >= regime_down else -1

            # Breakout confirmation: close must break prior bar's high (long) or low (short)
            if direction == 1 and close_price <= prior_high:
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return no_signal()
            if direction == -1 and close_price >= prior_low:
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return no_signal()

            contraction_count = len(contractions)
            signal_type = "vcp_breakout_long" if direction == 1 else "vcp_breakout_short"

            # ── Trade frame ────────────────────────────────────────────────
            frame = frame_trade(
                setup_type=signal_type,
                direction=direction,
                entry=close_price,
                features=features,
                atr=atr,
                regime_type=self.regime_type,
            )
            if not frame.viable:
                # Reset contractions
                contractions = [(bar_range, bar_volume)]
                state["contractions"] = contractions
                self._state[(symbol, tf)] = state
                return no_signal()

            # ── 4-factor confidence composite (NO HMM probability) ───────────
            # contraction_quality_score: number of contractions (more = stronger setup)
            contraction_quality_score = clamp01((contraction_count - min_contractions) / 4.0)

            # volume_expansion_score: how much did volume expand vs last contraction?
            volume_expansion_score = clamp01((bar_volume / max(last_vol, 1e-9) - 1.0) / 1.0)

            # breakout_margin_score: how far did price close beyond prior bar's range?
            if direction == 1:
                margin = close_price - prior_high
            else:
                margin = prior_low - close_price
            breakout_margin_score = clamp01(abs(margin) / atr) if atr > 0 else 0.5

            # range_compression_score: how compressed was the bar range vs ATR?
            # (tighter contraction = cleaner setup)
            range_compression_score = clamp01(1.0 - bar_range / atr) if atr > 0 else 0.5

            # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
            factor_scores = {
                "contraction_quality_score": round(contraction_quality_score, 4),
                "volume_expansion_score": round(volume_expansion_score, 4),
                "breakout_margin_score": round(breakout_margin_score, 4),
                "range_compression_score": round(range_compression_score, 4),
            }

            # Weights: 0.30 + 0.25 + 0.25 + 0.20 = 1.0
            raw_conf = (
                0.30 * contraction_quality_score
                + 0.25 * volume_expansion_score
                + 0.25 * breakout_margin_score
                + 0.20 * range_compression_score
            )

            supporting = [
                f"contraction_count={contraction_count}",
                f"expansion_range={bar_range:.2f}",
                f"expansion_vol={bar_volume:.0f}",
                f"last_contraction_vol={last_vol:.0f}",
                "volume_expansion_confirmed",
            ]
            raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
            confidence = compose_confidence(raw_conf)

            # ── Regime context ─────────────────────────────────────────────
            regime_ctx = "bullish" if direction == 1 else "bearish"

            # ── Clear contractions after fire ──────────────────────────────
            state["contractions"] = []
            self._state[(symbol, tf)] = state

            signal = make_signal_from_frame(
                frame,
                symbol=symbol,
                timeframe=features.get("timeframe", tf),
                timestamp=features.get("timestamp", ""),
                signal_type=signal_type,
                setup_plugin=self.name,
                direction=direction,
                confidence=confidence,
                regime_context=regime_ctx,
                supporting_factors=supporting,
                factor_scores=factor_scores,
            )
            signal["contraction_count"] = contraction_count
            return signal

        else:
            # Not a contraction, not a valid expansion -> reset
            contractions = [(bar_range, bar_volume)]
            state["contractions"] = contractions
            self._state[(symbol, tf)] = state
            return no_signal()

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VCPPlugin()
