"""trad_OFIContinuation — I7 trend setup consuming OFI I1 features.

Fires once per distinct OFI episode (onset of N-bar sustained directional flow).
Segment: trend regime only.

Renaissance principles:
- Segment relentlessly: fires only when OFI persists for N bars (not just 1 spike)
- Instrument everything: persistence count, EWMA magnitude all logged
- Earn the right through proof: requires N-bar confirmation before signal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import onset_guard, track_consecutive_state
from .trade_framer import frame_trade

if TYPE_CHECKING:
    pass

_MIN_BARS_DEFAULT: int = 10
_MAGNITUDE_FLOORS_DEFAULT: dict[str, float] = {
    "ES": 500.0,
    "NQ": 200.0,
    "CL": 1000.0,
    "GC": 500.0,
    "_default": 500.0,
}
# upper_ref = 4 * floor across all instruments (ratio is structurally stable)
_UPPER_REF_MULTIPLIER: float = 4.0


@dataclass
class OFIContinuationPlugin:
    """Trend setup: sustained directional OFI for N consecutive bars.

    Gates:
    - ofi_ewma_20 must have same sign for N consecutive bars
    - abs(ofi_ewma_20) must meet per-instrument floor
    - onset_guard: fires only on the bar the streak first crosses N

    onset_guard placed after ALL downstream gates — state commits only when signal emits.
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
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        min_bars: int = (
            cfg.get_sync("threshold.ofi_continuation.min_bars", _MIN_BARS_DEFAULT)
            if cfg
            else _MIN_BARS_DEFAULT
        )
        mag_floors: dict = (
            cfg.get_sync("threshold.ofi_continuation.magnitude_floors", _MAGNITUDE_FLOORS_DEFAULT)
            if cfg
            else _MAGNITUDE_FLOORS_DEFAULT
        )

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
        direction, count = track_consecutive_state(
            frames, self._state, state_key, current_dir, "dir"
        )

        mag_threshold = float(
            mag_floors.get(
                symbol, mag_floors.get("_default", _MAGNITUDE_FLOORS_DEFAULT["_default"])
            )
        )
        upper_ref = mag_threshold * _UPPER_REF_MULTIPLIER

        # onset_guard: called unconditionally so it sees False when streak drops below
        # min_bars or magnitude gate fails — enabling proper rearm on next episode.
        onset_key = f"{state_key}_onset"
        condition_active = count >= min_bars and abs(ofi_ewma) >= mag_threshold
        is_new_onset = onset_guard(self._state, onset_key, condition_active)
        if not condition_active or not is_new_onset:
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

        magnitude_score = clamp01(
            (abs(ofi_ewma) - mag_threshold) / max(1e-9, upper_ref - mag_threshold)
        )
        ofi_ewma5 = features.get("ofi_ewma_5")
        if ofi_ewma5 is not None:
            # gradient-exempt: binary alignment gate, not a continuous gradient
            alignment_score = 1.0 if float(ofi_ewma5) * ofi_ewma > 0 else 0.3  # gradient-exempt
        else:
            alignment_score = 0.65
        persistence_score = clamp01((count - min_bars) / max(1, min_bars))
        rel_vol = features.get("rel_volume")
        rel_vol = float(rel_vol) if rel_vol is not None else 1.0
        volume_score = clamp01((rel_vol - 1.0) / 1.5)

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
            symbol=frames.get("symbol", ""),
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
