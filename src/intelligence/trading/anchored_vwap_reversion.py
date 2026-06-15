"""trad_AnchoredVWAPReversion — I7 mean-reversion setup consuming I4 AnchoredVWAP fields.

Fires once per departure-and-return structural event: price must have departed from
session VWAP by >= N sigma AND is now returning with close confirmation (rejection/reclaim
candle). Displacement without return produces no signal.

Renaissance principles:
- Structural event gate: departure + return is the trigger, not displacement alone
- Segment relentlessly: fires only in ranging regime (hmm_regime=0)
- Earn the right through proof: sigma threshold + hurst < 0.55 required
- Reclaim candle required: close must confirm return direction (not just wick touch)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from ..utils import guard_intraday_only
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence, get_min_ctf_score
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade, targets_from_floats

if TYPE_CHECKING:
    pass

_SIGMA_MIN_DEFAULT: float = 1.5
_HURST_MAX_DEFAULT: float = 0.55


@dataclass
class VWAPReversionState:
    """Per-(symbol, timeframe) state for departure + return tracking."""

    # Ring buffer of recent sigma values for departure tracking
    sigma_buffer: deque = field(default_factory=lambda: deque(maxlen=50))
    # Sigma value captured at departure onset; None = not currently departed
    departure_sigma: float | None = None
    # Bars elapsed since departure (resets when departure_sigma cleared)
    departure_bars: int = 0


@dataclass
class AnchoredVWAPReversionPlugin:
    """Mean-reversion setup: fires once per departure-reversion structural event.

    Gates (in order):
    1. Departure FIRST: |session_vwap_deviation_sigma| >= sigma_min
    2. Return velocity SECOND: session_vwap_deviation_velocity toward VWAP
    3. Reclaim confirmation THIRD: close must cross back over VWAP (not wick-only)
    4. HMM context FOURTH: hmm_regime == 0 (ranging)
    5. Hurst context FIFTH: hurst_exponent < hurst_max (sub-random walk)
    6. deduplicate_event with (departure_sigma, reclaim_level)
    7. OHLCV extraction + trade frame
    8. Emit signal

    Direction:
    - sigma > 0 (price above VWAP) -> short (reversion down toward VWAP)
    - sigma < 0 (price below VWAP) -> long (reversion up toward VWAP)
    """

    name: str = "trad_AnchoredVWAPReversion"
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
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
    regime_type: str = "mean_reversion"
    requires_i6_confluence: bool = True
    _state: dict[str, VWAPReversionState] = field(default_factory=dict)
    # Separate namespace for deduplicate_event (needs plain dict entries, not VWAPReversionState)
    _dedup_state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_state(self, symbol: str, tf: str) -> VWAPReversionState:
        key = f"{symbol}_{tf}"
        if key not in self._state:
            self._state[key] = VWAPReversionState()
        return self._state[key]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        if not guard_intraday_only(frames):
            return no_signal()

        cfg = self._config_service
        sigma_min = (
            cfg.get_sync("threshold.vwap_reversion.sigma_min", _SIGMA_MIN_DEFAULT)
            if cfg
            else _SIGMA_MIN_DEFAULT
        )
        hurst_max = (
            cfg.get_sync("threshold.vwap_reversion.hurst_max", _HURST_MAX_DEFAULT)
            if cfg
            else _HURST_MAX_DEFAULT
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

        # ECL annotation: ctf_score is extrinsic context, not an emission gate (Phase 123)
        _ctf_raw = features.get("ctf_score")
        ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
        ctf_confirmed: bool | None = (
            (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
        )
        # No return no_signal() — signal fires if intrinsic criteria met

        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        state = self._get_state(symbol, tf_key)

        sigma = features.get("session_vwap_deviation_sigma")
        if sigma is None:
            return no_signal()
        sigma = float(sigma)

        # Update sigma buffer with current bar
        state.sigma_buffer.append(sigma)

        # Departure FIRST: price must be >= sigma_min away from VWAP
        if abs(sigma) < sigma_min:
            # Not departed: clear departure state so it re-arms on next departure
            state.departure_sigma = None
            state.departure_bars = 0
            return no_signal()

        # Track departure onset: first bar abs(sigma) >= sigma_min
        if state.departure_sigma is None:
            state.departure_sigma = abs(sigma)
            state.departure_bars = 0
        else:
            state.departure_bars += 1

        direction = -1 if sigma > 0 else 1

        # Return velocity SECOND: velocity must be toward VWAP (displacement unwinding)
        velocity = float(features.get("session_vwap_deviation_velocity", 0.0))
        velocity_toward_vwap = velocity < 0 if direction == -1 else velocity > 0
        if not velocity_toward_vwap:
            return no_signal()

        # Rejection/reclaim confirmation THIRD: close must confirm return direction
        # (not just a wick touching VWAP — close must cross back over VWAP)
        vwap = features.get("session_vwap")
        if vwap is None:
            return no_signal()
        vwap = float(vwap)

        close_arr = df["close"].to_numpy(dtype=float)
        current_close = float(close_arr[-1])

        if direction == -1:
            # Departed above VWAP (sigma > 0): reclaim = close crossed back below VWAP
            reclaim_confirmed = current_close < vwap
        else:
            # Departed below VWAP (sigma < 0): reclaim = close crossed back above VWAP
            reclaim_confirmed = current_close > vwap

        if not reclaim_confirmed:
            return no_signal()

        hmm = features.get("hmm_regime")
        hurst = features.get("hurst_exponent")
        if hmm is None or hurst is None:
            return no_signal()
        hmm = int(hmm)
        hurst = float(hurst)

        # HMM context FOURTH: ranging regime required
        if hmm != 0:
            return no_signal()

        # Hurst context FIFTH: sub-random walk confirms mean-reversion tendency
        if hurst >= hurst_max:
            return no_signal()

        # deduplicate_event by (departure_sigma, reclaim_level): prevents re-fire on same
        # displacement episode (same departure magnitude returning to same VWAP level).
        # Uses _dedup_state (plain dict) separate from _state (VWAPReversionState objects).
        event_id = (round(state.departure_sigma, 4), round(vwap, 4))
        if not deduplicate_event(self._dedup_state, state_key, event_id):
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = current_close

        setup_type = "vwap_reversion_short" if direction == -1 else "vwap_reversion_long"
        frame = frame_trade(
            setup_type=setup_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
            regime_type=self.regime_type,
        )
        if not frame.viable:
            return no_signal()

        avwap_upper = float(features.get("avwap_upper_band", 0.0))
        avwap_lower = float(features.get("avwap_lower_band", 0.0))

        targets: list[float] = []
        if vwap > 0:
            targets.append(round(vwap, 2))
        else:
            targets.append(round(frame.targets[0].price if frame.targets else 0.0, 2))
        if direction == -1 and avwap_lower > 0:
            targets.append(round(avwap_lower, 2))
        elif direction == 1 and avwap_upper > 0:
            targets.append(round(avwap_upper, 2))
        elif len(frame.targets) > 1:
            targets.append(round(frame.targets[1].price, 2))

        # Confidence: 3-factor composite: sigma_magnitude, hurst_quality, vol_stability.
        # Velocity is a structural gate (not a soft weight).
        sigma_magnitude = min(1.0, (abs(sigma) - sigma_min) / max(1e-9, sigma_min))
        hurst_mr_quality = float(features.get("hurst_mr_quality", 1.0 - hurst))
        hurst_quality = min(1.0, max(0.0, hurst_mr_quality))
        vol_regime = float(features.get("vol_regime", 0.5))
        vol_stability = 1.0 - abs(vol_regime - 0.5) * 2.0

        # Wave B: factor audit trail - pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "sigma_magnitude": round(sigma_magnitude, 4),
            "hurst_quality": round(hurst_quality, 4),
            "vol_stability": round(vol_stability, 4),
        }

        raw_conf = 0.40 * sigma_magnitude + 0.35 * hurst_quality + 0.25 * vol_stability

        supporting: list[str] = [
            f"session_vwap_deviation_sigma={sigma:.3f}",
            f"session_vwap_deviation_velocity={velocity:.4f}",
            f"hurst_exponent={hurst:.3f}",
            "velocity_toward_vwap",
            "reclaim_candle_confirmed",
        ]
        if sigma_magnitude > 0.5:
            supporting.append("sigma_extreme")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        _t_objs, _rr_t1, _rr_t2 = targets_from_floats(targets, frame.entry, frame.stop)
        _frame = dc_replace(frame, targets=_t_objs, rr_t1=_rr_t1, rr_t2=_rr_t2)
        signal = make_signal_from_frame(
            _frame,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=setup_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="ranging",
            supporting_factors=supporting,
            factor_scores=factor_scores,
            ctf_score=ctf_score,
            ctf_confirmed=ctf_confirmed,
        )
        ctx = capture_signal_features(features, direction, "mean_reversion", signal["confidence"])
        signal["features_snapshot"] = ctx
        signal["context_features"] = ctx
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AnchoredVWAPReversionPlugin()
