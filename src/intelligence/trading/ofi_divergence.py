"""trad_OFIDivergence — I7 mean-reversion setup consuming OFI I1 features.

Fires when OFI direction strongly disagrees with price direction.
The pre-computed ofi_divergence field from I1 OFIPlugin captures this signal.

Renaissance principles:
- Segment relentlessly: fires only on strong divergence (abs >= 1.5)
- Instrument everything: divergence magnitude logged in supporting factors
- Earn the right through proof: threshold is 1.5 (strong disagreement only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .trade_framer import frame_trade

_DIVERGENCE_THRESHOLD: float = 1.5


@dataclass
class OFIDivergencePlugin:
    """Mean-reversion setup: OFI direction strongly disagrees with price direction.

    Gate: abs(ofi_divergence) >= 1.5
    Direction: sign of ofi_divergence (positive OFI with negative price → long;
               negative OFI with positive price → short)
    Confidence: compose_confidence(0.45 + abs(ofi_divergence) * 0.15)
    """

    name: str = "trad_OFIDivergence"
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
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "ofi", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        ofi_div = features.get("ofi_divergence")
        if ofi_div is None:
            return no_signal()

        ofi_div = float(ofi_div)
        if abs(ofi_div) < _DIVERGENCE_THRESHOLD:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Direction: sign of ofi_divergence
        # ofi_divergence = ofi_dir - price_dir
        # Positive: OFI bullish but price bearish → expect price to follow OFI → long
        # Negative: OFI bearish but price bullish → expect price to follow OFI → short
        direction = 1 if ofi_div > 0 else -1

        confidence = compose_confidence(0.45 + abs(ofi_div) * 0.15)

        sig_type = signal_type_for_direction("ofi_divergence", direction)
        tf = frame_trade(sig_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()

        stop_loss = tf.stop
        targets = [t.price for t in tf.targets]

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
        supporting: list[str] = [
            f"ofi_divergence={ofi_div:.3f}",
        ]
        if hmm_regime is not None:
            supporting.append(f"hmm_regime={hmm_regime}")

        # exhaustion: not applicable — spike/divergence signals are regime-independent;
        # Phase 49 will learn gate behavior from shadow data
        signal = {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": float(stop_loss),
            "targets": [float(t) for t in targets],
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
