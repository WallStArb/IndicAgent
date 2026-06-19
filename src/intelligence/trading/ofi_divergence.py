"""trad_OFIDivergence — I7 price-discovery setup consuming continuous OFI I1 factor.

Fires when:
  1. abs(ofi_divergence) >= 1.5 — statistically extreme unconfirmed order flow
  2. sign(ofi_divergence) stable for >= 2 bars — persistence eliminates noise

Hypothesis H1 (price-discovery): informed order flow leads price; price will close
the gap in the direction of OFI within the signal TTL window.

ofi_divergence = ofi_spike_z - price_return_z (both 100-bar z-scores, from I1 OFIPlugin).

Renaissance principles:
- Continuous inputs — ofi_divergence is a real z-score factor, not a ternary sign diff
- Persistence before conviction — two bars minimum
- EWMA alignment is a soft factor, not a hard gate
- regime_type="any" — let outcome data decide which regimes this signal favours
- Instrument everything — peak_abs, bars_persistent, all EWMA values logged
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
    rel_volume_score,
)
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import track_consecutive_state
from .trade_framer import frame_trade

_MIN_DIVERGENCE: float = 1.5  # σ threshold — recalibrate from observed fire rate
_MIN_PERSISTENCE: int = 2  # consecutive bars required before firing


@dataclass
class OFIDivergencePlugin:
    """I7 price-discovery: continuous OFI z-score factor diverges from price z-score.

    Gate: abs(ofi_divergence) >= 1.5 AND sign stable >= 2 bars.
    Direction: sign(ofi_divergence) — H1, price follows order flow.
    Confidence: 4-factor intrinsic composite via compose_confidence().
    """

    name: str = "trad_OFIDivergence"
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
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "ofi", "price_discovery"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)
    # peak_abs tracked separately — track_consecutive_state overwrites the full state entry
    _peak_abs: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        min_persistence = (
            cfg.get_sync("threshold.ofi_divergence.min_persistence_bars", _MIN_PERSISTENCE)
            if cfg
            else _MIN_PERSISTENCE
        )
        min_divergence = (
            cfg.get_sync("threshold.ofi_divergence.min_divergence_sigma", _MIN_DIVERGENCE)
            if cfg
            else _MIN_DIVERGENCE
        )
        w_magnitude = cfg.get_sync("weights.ofi_divergence.magnitude", 0.40) if cfg else 0.40
        w_alignment = cfg.get_sync("weights.ofi_divergence.alignment", 0.25) if cfg else 0.25
        w_persistence = cfg.get_sync("weights.ofi_divergence.persistence", 0.20) if cfg else 0.20
        w_volume = cfg.get_sync("weights.ofi_divergence.volume", 0.15) if cfg else 0.15
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
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")

        if df is None or len(df) < self.min_lookback:
            return no_signal()

        ofi_div = features.get("ofi_divergence")
        if ofi_div is None:
            return no_signal()
        ofi_div = float(ofi_div)

        # ── Persistence tracking ─────────────────────────────────────────────
        div_sign = 1 if ofi_div > 0 else (-1 if ofi_div < 0 else 0)
        state_key = f"{symbol}_{tf}"

        if div_sign == 0:
            self._state.pop(state_key, None)
            self._peak_abs.pop(state_key, None)
            return no_signal()

        prev_sign = (self._state.get(state_key) or {}).get("div_sign", 0)
        _, count = track_consecutive_state(frames, self._state, state_key, div_sign, "div_sign")

        # Reset peak_abs when sign flips
        if div_sign != prev_sign:
            self._peak_abs[state_key] = abs(ofi_div)
        else:
            self._peak_abs[state_key] = max(self._peak_abs.get(state_key, 0.0), abs(ofi_div))

        peak_abs = self._peak_abs[state_key]

        # ── Gate checks ──────────────────────────────────────────────────────
        if abs(ofi_div) < min_divergence:
            return no_signal()
        if count < min_persistence:
            return no_signal()

        # ── Dual gate (before OHLCV/ATR access) ─────────────────────────────
        # Gate 1: regime gate (any-regime uses hmm_trending_weight)
        if hmm_trending_weight(features) < get_min_regime_weight():
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        direction = div_sign
        close = float(df["close"].iloc[-1])

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        ofi_ewma_5 = features.get("ofi_ewma_5")
        ofi_ewma_20 = features.get("ofi_ewma_20")
        v5 = float(ofi_ewma_5) if ofi_ewma_5 is not None else None
        v20 = float(ofi_ewma_20) if ofi_ewma_20 is not None else None
        ewma5_aligned = (v5 is not None) and (1 if v5 > 0 else -1) == direction
        ewma20_aligned = (v20 is not None) and (1 if v20 > 0 else -1) == direction

        magnitude_score = clamp01(math.tanh(peak_abs / 3.0))

        alignment_score = clamp01(
            (1.0 if ewma5_aligned else 0.3) * 0.6 + (1.0 if ewma20_aligned else 0.3) * 0.4
        )

        persistence_score = clamp01((count - min_persistence) / 5.0)

        volume_score = rel_volume_score(features)

        # Weights sum to 1.0
        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "magnitude_score": round(magnitude_score, 4),
            "alignment_score": round(alignment_score, 4),
            "persistence_score": round(persistence_score, 4),
            "volume_score": round(volume_score, 4),
        }

        raw_conf = (
            w_magnitude * magnitude_score
            + w_alignment * alignment_score
            + w_persistence * persistence_score
            + w_volume * volume_score
        )
        confidence = compose_confidence(raw_conf)

        # ── Trade frame ───────────────────────────────────────────────────────
        sig_type = signal_type_for_direction("ofi_divergence", direction)
        tf_frame = frame_trade(
            sig_type, direction, close, features, atr, regime_type=self.regime_type
        )
        if not tf_frame.viable:
            return no_signal()

        hmm_regime = features.get("hmm_regime")
        is_ranging = hmm_regime is not None and float(hmm_regime) == 0.0
        regime_context = "ranging" if is_ranging else "any"

        supporting: list[str] = [
            f"ofi_divergence={ofi_div:.3f}",
            f"peak_abs={peak_abs:.3f}",
            f"bars_persistent={count}",
        ]
        ofi_spike_z = features.get("ofi_spike_z")
        if ofi_spike_z is not None:
            supporting.append(f"ofi_spike_z={float(ofi_spike_z):.3f}")
        if ofi_ewma_5 is not None:
            supporting.append(f"ofi_ewma_5={float(ofi_ewma_5):.4f}")
        if ofi_ewma_20 is not None:
            supporting.append(f"ofi_ewma_20={float(ofi_ewma_20):.4f}")
        if hmm_regime is not None:
            supporting.append(f"hmm_regime={hmm_regime}")
        rel_vol = features.get("rel_volume")
        if rel_vol is not None:
            supporting.append(f"rel_volume={float(rel_vol):.2f}")

        signal = make_signal_from_frame(
            tf_frame,
            symbol=symbol,
            timeframe=features.get("timeframe", tf),
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIDivergencePlugin()
