"""I7 SessionExtremesSetup — fade setups triggered by price approaching Asian session extremes.

VERDICT: SCOPE-MISMATCH (Phase 126 audit)
  The gate requires asian_session_high and asian_session_low from I3/struct tier.
  SQL probe on 30-day corpus (2,222,900 bars): zero bars have asian_session_high populated
  in intelligence_features (column existence: 0/2,222,900). The current instrument universe
  (ES, NQ, RTY, EURUSD, USDJPY, USDCHF, SPY, etc.) does not include dedicated Asian-session
  FX or equity products that reliably publish Asian-session extremes.
  Gate logic is structurally correct; zero fires are expected until Asian-session instruments
  (e.g., NKD, NI225, USDJPY 24h FX) are added to the corpus.
  Set shadow_only=False when instruments with asian_session_high coverage are added.

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import (
    capture_signal_features,
    clamp01,
    compose_confidence,
    get_min_ctf_score,
    get_min_regime_weight,
)
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class SessionExtremesSetupPlugin:
    """I7 trading setup: fade when price approaches Asian session high or low during London/NY.

    SESS-01: Asian session H/L must be available from struct_SessionLevels.
    SESS-02: Signal only fires during London (03:00–12:00 ET) or NY session window.
    SESS-03: At least one confirming factor required: trend alignment, volume spike, or RSI extreme.

    Entry style: at_limit — limit order placed at the session extreme level.
    """

    name: str = "trad_SessionExtremesSetup"
    shadow_only: bool = True
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "bias",
            "proximity_atr",
            "confidence",
            "entry_type",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "session"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    requires_i6_confluence: bool = True
    proximity_atr_mult: float = 0.3
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        proximity_atr_mult = (
            cfg.get_sync("threshold.session_extremes.proximity_atr", self.proximity_atr_mult)
            if cfg
            else self.proximity_atr_mult
        )
        rsi_oversold = (
            cfg.get_sync("threshold.session_extremes.rsi_oversold", 35.0) if cfg else 35.0
        )
        rsi_overbought = (
            cfg.get_sync("threshold.session_extremes.rsi_overbought", 65.0) if cfg else 65.0
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
            return {}

        # SESS-01: Asian extremes must be available (cheap, no OHLCV required)
        asian_high = features.get("asian_session_high")
        asian_low = features.get("asian_session_low")
        if not isinstance(asian_high, (int, float)) or not isinstance(asian_low, (int, float)):
            return no_signal()

        # SESS-02: London or NY session only (cheap timing gate)
        session_london = float(features.get("session_london", 0.0))
        session_ny = float(features.get("session_ny", 0.0))
        if not (session_london or session_ny):
            return no_signal()

        # ── Dual gate (before OHLCV access) ─────────────────────────────────
        # Gate 1: mean_reversion regime gate — ranging probability >= threshold
        if hmm_regime_weight(features, "ranging") < get_min_regime_weight():
            return no_signal()

        # ECL annotation: ctf_score is extrinsic context, not an emission gate (Phase 123)
        _ctf_raw = features.get("ctf_score")
        ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
        ctf_confirmed: bool | None = (
            (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
        )
        # No return no_signal() — signal fires if intrinsic criteria met

        # ── ATR and price access (after dual gate) ───────────────────────────
        symbol = frames.get("symbol", "")
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # Gate 3: proximity to Asian extreme
        close = float(df["close"].iloc[-1])
        dist_high = abs(close - asian_high) / atr
        dist_low = abs(close - asian_low) / atr
        near_high = dist_high <= proximity_atr_mult
        near_low = dist_low <= proximity_atr_mult

        if not (near_high or near_low):
            return no_signal()

        # If simultaneously near both (very tight Asian range), pick closer
        if near_high and near_low:
            near_high = dist_high <= dist_low
            near_low = not near_high

        direction = -1 if near_high else 1  # fade: near high → short, near low → long
        proximity_atr = dist_high if near_high else dist_low

        # SESS-03: At least one confirming factor
        supporting: list[str] = []

        trend_regime = float(features.get("trend_regime", 0.0))
        trend_aligns = (direction == -1 and trend_regime < -0.3) or (
            direction == 1 and trend_regime > 0.3
        )
        if trend_aligns:
            supporting.append("trend_align")

        vol = df["volume"].to_numpy(dtype=float)
        vol_mean = float(np.mean(vol[-21:-1])) if len(vol) > 21 else float(np.mean(vol[:-1]))
        vol_spike = vol_mean > 0 and vol[-1] > 1.5 * vol_mean
        if vol_spike:
            supporting.append("volume_spike")

        rsi = features.get("rsi_14")
        rsi_extreme = isinstance(rsi, (int, float)) and (
            (direction == -1 and rsi > rsi_overbought) or (direction == 1 and rsi < rsi_oversold)
        )
        if rsi_extreme:
            supporting.append("rsi_extreme")

        if not supporting:
            return no_signal()

        # Entry, stop, targets
        entry_price = asian_high if near_high else asian_low

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        # level_proximity: how close price is to the extreme (closer = better)
        level_proximity = clamp01(1.0 - (proximity_atr / proximity_atr_mult))

        # rejection_strength: number of confirming factors as quality signal
        rejection_strength = clamp01(len(supporting) / 3.0)

        # session_timing_score: both sessions = best, single = moderate
        if session_london and session_ny:
            session_timing_score = 1.0
        else:
            session_timing_score = 0.65

        # volume_context: volume spike = high confirmation
        if vol_spike:
            volume_context = clamp01((float(vol[-1]) / max(1e-9, vol_mean) - 1.0) / 1.0)
        else:
            volume_context = 0.25

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "level_proximity": round(level_proximity, 4),
            "rejection_strength": round(rejection_strength, 4),
            "session_timing_score": round(session_timing_score, 4),
            "volume_context": round(volume_context, 4),
        }

        # Weights sum to 1.0
        raw_conf = (
            0.35 * level_proximity
            + 0.30 * rejection_strength
            + 0.20 * session_timing_score
            + 0.15 * volume_context
        )
        confidence = compose_confidence(raw_conf)

        extreme = "high" if near_high else "low"
        side = "short" if direction == -1 else "long"
        signal_type = f"session_extreme_{extreme}_fade_{side}"
        if session_london and session_ny:
            session_ctx = "both"
        elif session_london:
            session_ctx = "london"
        else:
            session_ctx = "ny"

        regime_ctx = f"session_extreme_{session_ctx}"
        supporting.append(f"session:{session_ctx}")

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(
            signal_type, direction, entry_price, features, atr, regime_type=self.regime_type
        )
        if not tf.viable:
            return no_signal()

        ctx = capture_signal_features(features, direction, "session", confidence)
        signal = make_signal_from_frame(
            tf,
            symbol=symbol,
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            features_snapshot=ctx,
            context_features=ctx,
            ctf_score=ctf_score,
            ctf_confirmed=ctf_confirmed,
            factor_scores=factor_scores,
        )
        signal["bias"] = side
        signal["proximity_atr"] = round(proximity_atr, 4)
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionExtremesSetupPlugin()
