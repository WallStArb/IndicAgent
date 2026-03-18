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

_MIN_CONSECUTIVE_BARS: int = 5


@dataclass
class OFIContinuationPlugin:
    """Trend setup: sustained directional OFI for N consecutive bars.

    Gates:
    - ofi_ewma_20 must have same sign for N=5 consecutive bars
    - State tracks consecutive directional bar count per (symbol, tf)

    Direction: sign of ofi_ewma_20
    Confidence: min(0.85, 0.50 + abs(ofi_ewma_20) * 0.001)
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
            return self._no_signal()

        ofi_ewma = features.get("ofi_ewma_20")
        if ofi_ewma is None:
            return self._no_signal()

        ofi_ewma = float(ofi_ewma)
        if ofi_ewma == 0.0:
            return self._no_signal()

        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        current_dir = 1 if ofi_ewma > 0 else -1

        # Update consecutive direction count
        state = self._state.get(state_key, {"dir": 0, "count": 0})
        if state["dir"] == current_dir:
            state["count"] += 1
        else:
            state["dir"] = current_dir
            state["count"] = 1
        self._state[state_key] = state

        # Gate: require N consecutive bars in same direction
        if state["count"] < _MIN_CONSECUTIVE_BARS:
            return self._no_signal()

        entry = float(df["close"].iloc[-1])

        direction = current_dir
        confidence = round(min(0.85, 0.50 + abs(ofi_ewma) * 0.001), 4)

        signal_type = "ofi_continuation_long" if direction == 1 else "ofi_continuation_short"
        hmm_regime = features.get("hmm_regime")

        supporting: list[str] = [
            f"ofi_ewma_20={ofi_ewma:.1f}",
            f"consecutive_bars={state['count']}",
        ]

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": None,
            "targets": None,
            "confidence": confidence,
            "regime_context": {"hmm_regime": hmm_regime},
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = OFIContinuationPlugin()
