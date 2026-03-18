"""trad_DualDivergence — I7 shadow plugin: both OFI AND CVD diverging simultaneously.

The highest-confidence microstructure divergence signal: requires both order flow
imbalance (OFI) AND cumulative volume delta (CVD) to disagree with price direction
for N consecutive confirmation bars.

Starts in SHADOW MODE (IS_SHADOW = True) to accumulate labeled training data
before live deployment. The signal_generator_service respects IS_SHADOW class
attribute to mark all entries from this plugin as is_shadow=True.

Renaissance principles:
- Earn the right through proof: shadow mode until statistical significance (p<0.05, N>=100)
- Segment relentlessly: dual confirmation gate — OFI AND CVD both diverging
- Instrument everything: both divergence values, slope, confirmation_bars all logged
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..plugins import InputSpec

_CONFIRMATION_BARS: int = 3
_OFI_DIV_THRESHOLD: float = 1.0   # minimum abs(ofi_divergence)
_CVD_DIV_THRESHOLD: float = 1.0   # minimum abs(cvd_divergence)


@dataclass
class DualDivergencePlugin:
    """Shadow I7 plugin: both OFI and CVD diverge simultaneously for N bars.

    Gates (all required):
    - abs(ofi_divergence) >= 1.0
    - abs(cvd_divergence) >= 1.0
    - Both disagree with price direction for N=3 consecutive bars
    - Both divergence directions must agree with each other

    IS_SHADOW = True: all entries from this plugin are written as is_shadow=True
    until promoted via promote_shadow.py after statistical validation.

    Direction: based on divergence direction (sign of ofi_divergence)
    Confidence: min(0.85, 0.60 + abs(ofi_divergence) * 0.05 + abs(cvd_divergence) * 0.05)
    """

    # Plugin-level shadow flag — ClassVar so it's not an instance field
    IS_SHADOW: ClassVar[bool] = True
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        ofi_div = features.get("ofi_divergence")
        cvd_div = features.get("cvd_divergence")

        if ofi_div is None or cvd_div is None:
            return self._no_signal()

        ofi_div = float(ofi_div)
        cvd_div = float(cvd_div)

        # Both must exceed their thresholds
        if abs(ofi_div) < _OFI_DIV_THRESHOLD or abs(cvd_div) < _CVD_DIV_THRESHOLD:
            return self._no_signal()

        # Both must agree in direction (both bearish or both bullish vs price)
        ofi_sign = 1 if ofi_div > 0 else -1
        cvd_sign = 1 if cvd_div > 0 else -1
        if ofi_sign != cvd_sign:
            # Disagreement invalidates accumulated confirmation count
            state_key = f"{frames.get('__symbol__', '_')}_{frames.get('__timeframe__', '_')}"
            self._state.pop(state_key, None)
            return self._no_signal()

        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        combined_sign = ofi_sign
        state = self._state.get(state_key, {"sign": 0, "count": 0})
        if state["sign"] == combined_sign:
            state["count"] += 1
        else:
            state["sign"] = combined_sign
            state["count"] = 1
        self._state[state_key] = state

        # Gate: require N confirmation bars
        if state["count"] < _CONFIRMATION_BARS:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Direction: sign of divergence (positive = bullish pressure vs price)
        direction = combined_sign

        confidence = round(
            min(0.85, 0.60 + abs(ofi_div) * 0.05 + abs(cvd_div) * 0.05),
            4,
        )

        signal_type = "dual_divergence_long" if direction == 1 else "dual_divergence_short"
        hmm_regime = features.get("hmm_regime")
        cvd_slope = features.get("cvd_slope_5bar")
        ofi_ewma = features.get("ofi_ewma_20")

        supporting: list[str] = [
            f"ofi_divergence={ofi_div:.3f}",
            f"cvd_divergence={cvd_div:.3f}",
            f"confirmation_bars={state['count']}",
        ]
        if cvd_slope is not None:
            supporting.append(f"cvd_slope_5bar={float(cvd_slope):.1f}")
        if ofi_ewma is not None:
            supporting.append(f"ofi_ewma_20={float(ofi_ewma):.1f}")

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


plugin = DualDivergencePlugin()
