"""trad_DualDivergence — I7 plugin: both OFI AND CVD diverging simultaneously.

The highest-confidence microstructure divergence signal: requires both order flow
imbalance (OFI) AND cumulative volume delta (CVD) to disagree with price direction
for N consecutive confirmation bars.

Renaissance principles:
- Segment relentlessly: dual confirmation gate — OFI AND CVD both diverging
- Instrument everything: both divergence values, slope, confirmation_bars all logged
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import reset_consecutive_state, track_consecutive_state
from .trade_framer import frame_trade

_CONFIRMATION_BARS: int = 3
_OFI_DIV_THRESHOLD: float = 1.0  # minimum abs(ofi_divergence)
_CVD_DIV_THRESHOLD: float = 1.0  # minimum abs(cvd_divergence)

_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25


@dataclass
class DualDivergencePlugin:
    """I7 plugin: both OFI and CVD diverge simultaneously for N bars.

    Gates (all required):
    - abs(ofi_divergence) >= 1.0
    - abs(cvd_divergence) >= 1.0
    - Both disagree with price direction for N=3 consecutive bars
    - Both divergence directions must agree with each other
    - hmm_regime_weight(features, "ranging") >= 0.30 (mean_reversion: ranging gate)
    - abs(ctf_score) >= 0.25 (I6 confluence gate)

    Direction: based on divergence direction (sign of ofi_divergence)
    Confidence: 4-factor composite (ofi_divergence, cvd_divergence, confirmation_bars, volume)
    """

    name: str = "trad_DualDivergence"
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
    capability_tags: frozenset[str] = frozenset(
        {"trading", "divergence", "ofi", "cvd", "mean_reversion"}
    )
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    requires_i6_confluence: bool = True
    _state: dict = field(default_factory=dict)

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
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        ofi_div = features.get("ofi_divergence")
        cvd_div = features.get("cvd_divergence")

        if ofi_div is None or cvd_div is None:
            return no_signal()

        ofi_div = float(ofi_div)
        cvd_div = float(cvd_div)

        # Both must exceed their thresholds
        if abs(ofi_div) < _OFI_DIV_THRESHOLD or abs(cvd_div) < _CVD_DIV_THRESHOLD:
            return no_signal()

        # Both must agree in direction (both bearish or both bullish vs price)
        ofi_sign = 1 if ofi_div > 0 else -1
        cvd_sign = 1 if cvd_div > 0 else -1
        if ofi_sign != cvd_sign:
            # Disagreement invalidates accumulated confirmation count
            reset_consecutive_state(frames, self._state)
            return no_signal()

        # ── Gate 1: ranging regime gate (mean_reversion uses "ranging") ──────
        if hmm_regime_weight(features, "ranging") < _MIN_REGIME_WEIGHT:
            return no_signal()

        # ── Gate 2: I6 ctf_score gate ─────────────────────────────────────────
        ctf_score = float(features.get("ctf_score") or 0.0)
        if abs(ctf_score) < _MIN_CTF_SCORE:
            return no_signal()

        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        combined_sign = ofi_sign
        _, count = track_consecutive_state(frames, self._state, state_key, combined_sign, "sign")

        # Gate: require N confirmation bars
        if count < _CONFIRMATION_BARS:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Direction: sign of divergence (positive = bullish pressure vs price)
        direction = combined_sign

        # ── 4-factor confidence composite (NO HMM probability) ───────────────
        # ofi_divergence_score: magnitude of OFI divergence (tanh saturation)
        ofi_divergence_score = clamp01(math.tanh(abs(ofi_div) / 3.0))

        # cvd_divergence_score: magnitude of CVD divergence (tanh saturation)
        cvd_divergence_score = clamp01(math.tanh(abs(cvd_div) / 3.0))

        # confirmation_bars_score: how many bars confirmed (more = more persistent divergence)
        confirmation_bars_score = clamp01((count - _CONFIRMATION_BARS) / 5.0)

        # volume_score: relative volume (higher vol = more conviction behind divergence)
        rel_vol = features.get("rel_volume")
        volume_score = clamp01((float(rel_vol) - 1.0) / 1.5) if rel_vol is not None else 0.3

        # Weights: 0.35 + 0.30 + 0.20 + 0.15 = 1.0
        raw_conf = (
            0.35 * ofi_divergence_score
            + 0.30 * cvd_divergence_score
            + 0.20 * confirmation_bars_score
            + 0.15 * volume_score
        )

        confidence = compose_confidence(raw_conf)

        sig_type = signal_type_for_direction("dual_divergence", direction)
        tf_result = frame_trade(
            sig_type, direction, entry, features, atr, regime_type=self.regime_type
        )
        if not tf_result.viable:
            return no_signal()

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
        cvd_slope = features.get("cvd_slope_5bar")
        ofi_ewma = features.get("ofi_ewma_20")

        supporting: list[str] = [
            f"ofi_divergence={ofi_div:.3f}",
            f"cvd_divergence={cvd_div:.3f}",
            f"confirmation_bars={count}",
        ]
        if cvd_slope is not None:
            supporting.append(f"cvd_slope_5bar={float(cvd_slope):.1f}")
        if ofi_ewma is not None:
            supporting.append(f"ofi_ewma_20={float(ofi_ewma):.1f}")

        # exhaustion: not applicable — spike/divergence signals are regime-independent;
        # Phase 49 will learn gate behavior from shadow data
        signal = make_signal_from_frame(
            tf_result,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin="trad_DualDivergence",
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting,
        )
        signal["features_snapshot"] = capture_signal_features(
            features,
            direction,
            "microstructure",
            signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = DualDivergencePlugin()
