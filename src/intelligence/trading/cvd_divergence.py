"""trad_CVDDivergence — I7 mean-reversion setup consuming CVD I1 features.

Fires when Cumulative Volume Delta direction disagrees with price direction
for N consecutive bars of confirmation. Also logs dual_divergence flag when
both OFI and CVD are diverging simultaneously.

Renaissance principles:
- Segment relentlessly: requires N=3 bar confirmation (not just 1-bar divergence)
- Instrument everything: dual_divergence flag always logged on signal fire
- Earn the right through proof: requires persistence before signal fires
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_confluence_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .trade_framer import frame_trade

_CONFIRMATION_BARS: int = 3
_CVD_DIV_THRESHOLD: float = 0.0  # any nonzero divergence qualifies
_OFI_DUAL_THRESHOLD: float = 1.0  # OFI must also diverge at this level for dual flag


@dataclass
class CVDDivergencePlugin:
    """Mean-reversion setup: CVD slope opposes price direction for N bars.

    Gates:
    - cvd_divergence != 0 (CVD direction disagrees with price direction)
    - N=3 consecutive bars of confirmation
    (cvd_slope_5bar is logged in supporting_factors but not used as a gate)

    Additional metadata (always logged when signal fires):
    - dual_divergence = (abs(ofi_divergence) >= 1.0 AND abs(cvd_divergence) >= 1.0)

    Direction: opposite of price direction (mean reversion)
    Confidence: compose_confidence(base 0.55, +0.10 if dual_divergence,
    +0.05 per extra bar beyond N)
    """

    name: str = "trad_CVDDivergence"
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
            "dual_divergence",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "cvd", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        cvd_div = features.get("cvd_divergence")
        cvd_slope = features.get("cvd_slope_5bar")

        if cvd_div is None:
            return no_signal()

        cvd_div = float(cvd_div)
        if cvd_div == 0.0:
            # Zero CVD divergence invalidates any accumulated confirmation count
            state_key = f"{frames.get('__symbol__', '_')}_{frames.get('__timeframe__', '_')}"
            self._state.pop(state_key, None)
            return no_signal()

        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf}"

        cvd_div_sign = 1 if cvd_div > 0 else -1
        state = self._state.get(state_key, {"div_sign": 0, "count": 0})

        if state["div_sign"] == cvd_div_sign:
            state["count"] += 1
        else:
            state["div_sign"] = cvd_div_sign
            state["count"] = 1
        self._state[state_key] = state

        # Gate: require N confirmation bars
        if state["count"] < _CONFIRMATION_BARS:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # Direction: opposite of price direction (mean reversion)
        # cvd_divergence = slope_dir - price_dir_5bar
        # Positive: CVD bullish vs price bearish → price should revert up → long
        # Negative: CVD bearish vs price bullish → price should revert down → short
        direction = 1 if cvd_div > 0 else -1

        # Check dual divergence
        ofi_div = features.get("ofi_divergence")
        ofi_div_f = float(ofi_div) if ofi_div is not None else 0.0
        dual_divergence = (
            abs(ofi_div_f) >= _OFI_DUAL_THRESHOLD and abs(cvd_div) >= _OFI_DUAL_THRESHOLD
        )

        # Confidence
        extra_bars = max(0, state["count"] - _CONFIRMATION_BARS)
        raw_conf = 0.55
        if dual_divergence:
            raw_conf += 0.10
        raw_conf += extra_bars * 0.05
        confidence = compose_confidence(raw_conf)

        sig_type = signal_type_for_direction("cvd_divergence", direction)
        tf_result = frame_trade(sig_type, direction, entry, features, atr)
        if not tf_result.viable:
            return no_signal()

        stop_loss = tf_result.stop
        targets = [t.price for t in tf_result.targets]

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        supporting: list[str] = [
            f"cvd_divergence={cvd_div:.3f}",
            f"confirmation_bars={state['count']}",
        ]
        if cvd_slope is not None:
            supporting.append(f"cvd_slope_5bar={float(cvd_slope):.1f}")
        if dual_divergence:
            supporting.append("dual_divergence_confirmed")

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
            "dual_divergence": dual_divergence,
        }
        signal["_shadow"] = capture_confluence_features(
            features, direction, "microstructure", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CVDDivergencePlugin()
