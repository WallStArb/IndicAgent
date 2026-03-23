"""trad_OFIContinuation — I7 trend setup consuming OFI I1 features.

Fires when sustained directional Order Flow Imbalance persists over N consecutive bars.
Segment: trend regime only. Idea: persistent directional OFI signals informed participants
are committed to a direction — not just a one-bar spike but sustained conviction.

Renaissance principles:
- Segment relentlessly: fires only when OFI persists for N bars (not just 1 spike)
- Instrument everything: persistence count, EWMA magnitude all logged
- Earn the right through proof: requires N=5 bar confirmation before signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import no_signal, signal_type_for_direction
from .state_utils import track_consecutive_state
from .trade_framer import frame_trade

_MIN_CONSECUTIVE_BARS: int = 5


@dataclass
class OFIContinuationPlugin:
    """Trend setup: sustained directional OFI for N consecutive bars.

    Gates:
    - ofi_ewma_20 must have same sign for N=5 consecutive bars
    - State tracks consecutive directional bar count per (symbol, tf)

    Direction: sign of ofi_ewma_20
    Confidence: compose_confidence(0.50 + abs(ofi_ewma_20) * 0.001)
    """

    name: str = "trad_OFIContinuation"
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
    capability_tags: frozenset[str] = frozenset({"trading", "continuation", "ofi"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        ofi_ewma = features.get("ofi_ewma_20")
        if ofi_ewma is None:
            return no_signal()

        ofi_ewma = float(ofi_ewma)
        if ofi_ewma == 0.0:
            return no_signal()

        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        current_dir = 1 if ofi_ewma > 0 else -1

        # Update consecutive direction count
        direction, count = track_consecutive_state(
            frames, self._state, state_key, current_dir, "dir"
        )

        # Gate: require N consecutive bars in same direction
        if count < _MIN_CONSECUTIVE_BARS:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        entry = float(df["close"].iloc[-1])

        sig_type = signal_type_for_direction("ofi_continuation", direction)
        tf_result = frame_trade(sig_type, direction, entry, features, atr)
        if not tf_result.viable:
            return no_signal()

        stop_loss = tf_result.stop
        targets = [t.price for t in tf_result.targets]

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        supporting: list[str] = [
            f"ofi_ewma_20={ofi_ewma:.1f}",
            f"consecutive_bars={count}",
        ]

        raw_conf = 0.50 + abs(ofi_ewma) * 0.001
        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

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


plugin = OFIContinuationPlugin()
