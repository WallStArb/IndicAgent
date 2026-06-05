"""trad_DualDivergence — I7 plugin: both OFI AND CVD diverging simultaneously.

The highest-confidence microstructure divergence signal: requires both order flow
imbalance (OFI) AND cumulative volume delta (CVD) to disagree with price direction
for N consecutive confirmation bars.

Renaissance principles:
- Segment relentlessly: dual confirmation gate — OFI AND CVD both diverging
- Instrument everything: both divergence values, slope, confirmation_bars all logged
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import reset_consecutive_state, track_consecutive_state
from .trade_framer import frame_trade

_CONFIRMATION_BARS: int = 3
_OFI_DIV_THRESHOLD: float = 1.0  # minimum abs(ofi_divergence)
_CVD_DIV_THRESHOLD: float = 1.0  # minimum abs(cvd_divergence)


@dataclass
class DualDivergencePlugin:
    """I7 plugin: both OFI and CVD diverge simultaneously for N bars.

    Gates (all required):
    - abs(ofi_divergence) >= 1.0
    - abs(cvd_divergence) >= 1.0
    - Both disagree with price direction for N=3 consecutive bars
    - Both divergence directions must agree with each other

    Direction: based on divergence direction (sign of ofi_divergence)
    Confidence: compose_confidence(0.60 + abs(ofi_divergence) * 0.05 + abs(cvd_divergence) * 0.05)
    """

    name: str = "trad_DualDivergence"
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

        confidence = compose_confidence(0.60 + abs(ofi_div) * 0.05 + abs(cvd_div) * 0.05)

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
