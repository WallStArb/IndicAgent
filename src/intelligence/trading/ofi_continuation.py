"""trad_OFIContinuation — I7 trend setup consuming OFI I1 features.

Fires when sustained directional Order Flow Imbalance persists over N consecutive bars.
Segment: trend regime only. Idea: persistent directional OFI signals informed participants
are committed to a direction — not just a one-bar spike but sustained conviction.

Renaissance principles:
- Segment relentlessly: fires only when OFI persists for N bars (not just 1 spike)
- Instrument everything: persistence count, EWMA magnitude all logged
- Earn the right through proof: requires N=10 bar confirmation before signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import track_consecutive_state
from .trade_framer import frame_trade

_MIN_CONSECUTIVE_BARS: int = 10

# Phase 118 starting defaults from 90-day p75/p90 distribution — shadow mode will refine.
# DB query returned no rows (OFI not written to intelligence_features in historical data);
# using documented starting values from RCA analysis.
# Each entry: (p75_magnitude_gate, p90_upper_ref)
_OFI_PARAMS: dict[str, tuple[float, float]] = {
    "ES": (500.0, 2000.0),
    "NQ": (200.0, 800.0),
    "CL": (1000.0, 4000.0),
    "GC": (500.0, 2000.0),
}
_OFI_PARAMS_DEFAULT: tuple[float, float] = (500.0, 2000.0)


@dataclass
class OFIContinuationPlugin:
    """Trend setup: sustained directional OFI for N consecutive bars.

    Gates:
    - ofi_ewma_20 must have same sign for N=10 consecutive bars
    - abs(ofi_ewma_20) must meet per-instrument p75 magnitude floor
    - State tracks consecutive directional bar count per (symbol, tf)

    Direction: sign of ofi_ewma_20
    Confidence: 4-factor intrinsic composite via compose_confidence()
    """

    name: str = "trad_OFIContinuation"
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
    capability_tags: frozenset[str] = frozenset({"trading", "continuation", "ofi"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
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

        # Gate: require minimum OFI magnitude (trivial flow imbalances rejected)
        mag_threshold, upper_ref = _OFI_PARAMS.get(symbol, _OFI_PARAMS_DEFAULT)
        if abs(ofi_ewma) < mag_threshold:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = float(df["close"].iloc[-1])

        sig_type = signal_type_for_direction("ofi_continuation", direction)
        tf_result = frame_trade(
            sig_type, direction, entry, features, atr, regime_type=self.regime_type
        )
        if not tf_result.viable:
            return no_signal()

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        # --- 4-factor intrinsic confidence composite ---
        # ofi_ewma_5 confirmed emitted by I1 ofi.py (ofi_ewma_5 key, line 110);
        # using primary 4-factor formula with alignment_score.

        magnitude_score = clamp01(
            (abs(ofi_ewma) - mag_threshold) / max(1e-9, upper_ref - mag_threshold)
        )

        ofi_ewma5 = features.get("ofi_ewma_5")
        if ofi_ewma5 is not None:
            alignment_score = (
                1.0 if float(ofi_ewma5) * ofi_ewma > 0 else 0.3
            )  # gradient-exempt — direction alignment gate
        else:
            alignment_score = 0.65  # neutral fallback when ofi_ewma_5 missing

        persistence_score = clamp01((count - _MIN_CONSECUTIVE_BARS) / 10.0)

        rel_vol = features.get("rel_volume")
        rel_vol = float(rel_vol) if rel_vol is not None else 1.0
        volume_score = clamp01((rel_vol - 1.0) / 1.5)

        # Weighted sum — weights sum to 1.0; all factors clamped to [0,1] before entry
        raw_conf = (
            0.40 * magnitude_score
            + 0.25 * alignment_score
            + 0.20 * persistence_score
            + 0.15 * volume_score
        )

        confidence = compose_confidence(raw_conf)

        supporting: list[str] = [
            f"ofi_ewma_20={ofi_ewma:.1f}",
            f"consecutive_bars={count}",
            f"magnitude_score={magnitude_score:.3f}",
            f"persistence_score={persistence_score:.3f}",
        ]

        signal = make_signal_from_frame(
            tf_result,
            symbol=symbol,
            timeframe=tf,
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting,
            features_snapshot=capture_signal_features(
                features, direction, "microstructure", confidence
            ),
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIContinuationPlugin()
