"""trad_OFIContinuation -- I7 trend setup consuming OFI I1 features.

Fires on fresh OFI acceleration or volume thrust on top of sustained directional flow.
Segment: trend regime only.

Renaissance principles:
- Structural trigger, not state trigger: acceleration/thrust event anchors the hypothesis
- Streak is context (sustained imbalance must already exist), not the trigger
- Instrument everything: persistence count, EWMA magnitude, acceleration, volume ratio all logged
- Earn the right through proof: structural thrust + N-bar confirmation
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import clamp01, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event, track_consecutive_state
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

# Volume spike threshold: 2x average volume confirms structural thrust
_VOLUME_SPIKE_RATIO: float = 2.0

# Acceleration threshold as a fraction of the magnitude floor
# (10% of floor == meaningful acceleration, not noise)
_ACCELERATION_FLOOR_FRACTION: float = 0.10

# Minimum EWMA buffer depth before acceleration is computable
_EWMA_MIN_HISTORY: int = 5


@dataclass
class OFIContinuationState:
    """Per (symbol, timeframe) state for OFI acceleration detection.

    ewma_buffer: rolling window of ofi_ewma_20 values for second-derivative detection.
    last_acceleration_bar: call_count at last acceleration fire (dedup reference).
    """

    ewma_buffer: deque = field(default_factory=lambda: deque(maxlen=20))
    last_acceleration_bar: int | None = None


@dataclass
class OFIContinuationPlugin:
    """Trend setup: OFI acceleration or volume thrust on top of N-bar sustained flow.

    Gates (in order):
    1. Magnitude gate FIRST  -- abs(ofi_ewma_20) >= per-instrument floor
    2. Structural trigger SECOND -- EWMA acceleration OR volume spike (new structural event)
    3. Context filter THIRD  -- count >= min_bars AND direction sustained
    4. HMM regime gate: handled by aggregator via regime_type="trend"; not called here
    5. OHLCV + trade frame FIFTH
    6. deduplicate_event SIXTH -- prevent re-fire within _DEDUP_MIN_BARS of same direction
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
    _state: dict = field(default_factory=dict)
    _accel_state: dict[str, OFIContinuationState] = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_ofi_state(self, symbol: str, tf: str) -> OFIContinuationState:
        key = f"{symbol}_{tf}"
        if key not in self._accel_state:
            self._accel_state[key] = OFIContinuationState()
        return self._accel_state[key]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        min_bars: int = int(
            cfg.get_sync("threshold.ofi_continuation.min_bars", _MIN_BARS_DEFAULT)
            if cfg
            else _MIN_BARS_DEFAULT
        )
        mag_floors: dict = (
            cfg.get_sync("threshold.ofi_continuation.magnitude_floors", _MAGNITUDE_FLOORS_DEFAULT)
            if cfg
            else _MAGNITUDE_FLOORS_DEFAULT
        )
        ewma_min_history: int = int(
            cfg.get_sync("threshold.ofi_continuation.ewma_min_history", _EWMA_MIN_HISTORY)
            if cfg
            else _EWMA_MIN_HISTORY
        )
        volume_spike_ratio: float = float(
            cfg.get_sync("threshold.ofi_continuation.volume_spike_ratio", _VOLUME_SPIKE_RATIO)
            if cfg
            else _VOLUME_SPIKE_RATIO
        )
        accel_floor_fraction: float = float(
            cfg.get_sync(
                "threshold.ofi_continuation.acceleration_floor_fraction",
                _ACCELERATION_FLOOR_FRACTION,
            )
            if cfg
            else _ACCELERATION_FLOOR_FRACTION
        )
        upper_ref_mult: float = float(
            cfg.get_sync("threshold.ofi_continuation.upper_ref_multiplier", _UPPER_REF_MULTIPLIER)
            if cfg
            else _UPPER_REF_MULTIPLIER
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
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
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
        upper_ref = mag_threshold * upper_ref_mult

        # Magnitude gate FIRST -- floor filter; rejects noise before any state is committed
        if abs(ofi_ewma) < mag_threshold:
            return no_signal()

        # Update EWMA buffer after magnitude gate so history only accumulates on valid bars
        ofi_state = self._get_ofi_state(symbol, tf)
        ofi_state.ewma_buffer.append(ofi_ewma)

        # Structural trigger SECOND -- EWMA acceleration OR volume spike
        acceleration_confirmed = False
        volume_spike = False

        # Acceleration = second derivative (change-of-change) of ofi_ewma_20
        if len(ofi_state.ewma_buffer) >= ewma_min_history:
            buf = ofi_state.ewma_buffer
            ewma_change = buf[-1] - buf[-2]
            ewma_change_prev = buf[-2] - buf[-3]
            acceleration = ewma_change - ewma_change_prev
            directional_acceleration = (acceleration > 0 and ofi_ewma > 0) or (
                acceleration < 0 and ofi_ewma < 0
            )
            if (
                directional_acceleration
                and abs(acceleration) >= mag_threshold * accel_floor_fraction
            ):
                acceleration_confirmed = True

        current_vol = float(df["volume"].iloc[-1])
        vol_sma = features.get("volume_sma_20")
        vol_ratio = current_vol / float(vol_sma) if vol_sma and float(vol_sma) > 0 else 1.0
        if vol_ratio >= volume_spike_ratio:
            volume_spike = True

        if not acceleration_confirmed and not volume_spike:
            return no_signal()

        # Context filter THIRD -- OFI streak must show sustained directional flow
        if count < min_bars:
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

        # deduplicate_event SIXTH -- prevent re-fire within _DEDUP_MIN_BARS of same direction
        dedup_key = f"{state_key}_dedup"
        if not deduplicate_event(self._state, dedup_key, direction):
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

        # Wave B: factor audit trail -- pre-composite [0,1] scores (Phase 123)
        trigger_type = "acceleration" if acceleration_confirmed else "volume_spike"
        factor_scores = {
            "magnitude_score": round(magnitude_score, 4),
            "alignment_score": round(alignment_score, 4),
            "persistence_score": round(persistence_score, 4),
            "volume_score": round(volume_score, 4),
            "trigger_acceleration": 1.0 if acceleration_confirmed else 0.0,
        }

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
            f"trigger={trigger_type}",
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
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIContinuationPlugin()
