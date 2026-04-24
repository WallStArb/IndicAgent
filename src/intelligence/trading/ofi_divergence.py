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
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .state_utils import track_consecutive_state
from .trade_framer import frame_trade

_MIN_DIVERGENCE: float = 1.5   # σ threshold — recalibrate from observed fire rate
_MIN_PERSISTENCE: int = 2       # consecutive bars required before firing


@dataclass
class OFIDivergencePlugin:
    """I7 price-discovery: continuous OFI z-score factor diverges from price z-score.

    Gate: abs(ofi_divergence) >= 1.5 AND sign stable >= 2 bars.
    Direction: sign(ofi_divergence) — H1, price follows order flow.
    Confidence: tanh-weighted magnitude + soft EWMA and regime factors.
    """

    name: str = "trad_OFIDivergence"
    outputs: frozenset[str] = frozenset({
        "signal_type",
        "direction",
        "entry_price",
        "stop_loss",
        "targets",
        "confidence",
        "regime_context",
        "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "ofi", "price_discovery"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)
    # peak_abs tracked separately — track_consecutive_state overwrites the full state entry
    _peak_abs: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
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
        if abs(ofi_div) < _MIN_DIVERGENCE:
            return no_signal()
        if count < _MIN_PERSISTENCE:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        direction = div_sign
        close = float(df["close"].iloc[-1])

        # ── Confidence: continuous, magnitude-weighted ────────────────────────
        confidence = 0.42
        confidence += 0.25 * math.tanh(peak_abs / 3.0)   # principled soft cap

        ofi_ewma_5 = features.get("ofi_ewma_5")
        ofi_ewma_20 = features.get("ofi_ewma_20")
        v5 = float(ofi_ewma_5) if ofi_ewma_5 is not None else None
        v20 = float(ofi_ewma_20) if ofi_ewma_20 is not None else None
        ewma5_sign = (1 if v5 > 0 else (-1 if v5 < 0 else 0)) if v5 is not None else 0
        ewma20_sign = (1 if v20 > 0 else (-1 if v20 < 0 else 0)) if v20 is not None else 0

        # Fast EWMA: soft factor (boost or reduce), NOT a hard gate
        if ewma5_sign == direction:
            confidence += 0.08
        elif ewma5_sign != 0:
            confidence -= 0.04

        # Slow EWMA confirms sustained pressure
        if ewma5_sign == ewma20_sign and ewma5_sign != 0:
            confidence += 0.06

        rel_volume = features.get("rel_volume")
        if rel_volume is not None and float(rel_volume) >= 1.5:
            confidence += 0.06

        hmm_regime = features.get("hmm_regime")
        if hmm_regime is not None:
            r = float(hmm_regime)
            # Continuous regime weighting (regime_type="any")
            ranging_w = hmm_regime_weight(features, "ranging")
            trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
            confidence += 0.06 * ranging_w   # ranging — soft positive hint
            confidence -= 0.06 * trending_w  # trending — soft negative hint

        confidence = compose_confidence(confidence)

        # ── Trade frame ───────────────────────────────────────────────────────
        sig_type = signal_type_for_direction("ofi_divergence", direction)
        tf_frame = frame_trade(sig_type, direction, close, features, atr)
        if not tf_frame.viable:
            return no_signal()

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
        if rel_volume is not None:
            supporting.append(f"rel_volume={float(rel_volume):.2f}")

        signal = {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(close, 2),
            "stop_loss": float(tf_frame.stop),
            "targets": [float(t.price) for t in tf_frame.targets],
            "confidence": confidence,
            "regime_context": regime_context,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "microstructure", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIDivergencePlugin()
