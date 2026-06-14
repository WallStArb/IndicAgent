"""trad_AnchoredVWAPReversion — I7 mean-reversion setup consuming I4 AnchoredVWAP fields.

Fires once per displacement-and-reverting onset: price must be significantly displaced
from session VWAP AND already moving back toward it in a ranging regime.

Renaissance principles:
- Segment relentlessly: fires only in ranging regime (hmm_regime=0)
- Earn the right through proof: sigma threshold + hurst < 0.55 required
- No state, no state: velocity is a hard gate (displacement alone is not a setup)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from ..utils import guard_intraday_only
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .state_utils import onset_guard
from .trade_framer import frame_trade, targets_from_floats

if TYPE_CHECKING:
    pass

_SIGMA_MIN_DEFAULT: float = 1.5
_HURST_MAX_DEFAULT: float = 0.55


@dataclass
class AnchoredVWAPReversionPlugin:
    """Mean-reversion setup: fires once per displacement-reversion onset.

    Gates:
    - |session_vwap_deviation_sigma| >= sigma_min (price significantly displaced)
    - hmm_regime == 0 (ranging)
    - hurst_exponent < hurst_max (sub-random walk confirms mean-reversion)
    - session_vwap_deviation_velocity toward VWAP (hard gate — displacement must be unwinding)

    Direction:
    - sigma > 0 (price above VWAP) → short
    - sigma < 0 (price below VWAP) → long

    onset_guard placed after ALL downstream gates — state commits only when signal emits.
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
    requires_i6_confluence: bool = False  # exempt: see _I7_I6_EXEMPT in register_plugins.py
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

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

        sigma = features.get("session_vwap_deviation_sigma")
        hmm = features.get("hmm_regime")
        hurst = features.get("hurst_exponent")

        if sigma is None or hmm is None or hurst is None:
            return no_signal()

        sigma = float(sigma)
        hmm = int(hmm)
        hurst = float(hurst)

        direction = -1 if sigma > 0 else 1
        velocity = float(features.get("session_vwap_deviation_velocity", 0.0))
        velocity_toward_vwap = velocity < 0 if direction == -1 else velocity > 0

        # onset_guard called unconditionally with cheap condition so it sees False
        # when displacement clears or velocity reverses — enabling proper rearm.
        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        condition_active = (
            abs(sigma) >= sigma_min and hmm == 0 and hurst < hurst_max and velocity_toward_vwap
        )
        is_new_onset = onset_guard(self._state, state_key, condition_active)
        if not condition_active or not is_new_onset:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

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

        session_vwap = float(features.get("session_vwap", 0.0))
        avwap_upper = float(features.get("avwap_upper_band", 0.0))
        avwap_lower = float(features.get("avwap_lower_band", 0.0))

        targets: list[float] = []
        if session_vwap > 0:
            targets.append(round(session_vwap, 2))
        else:
            targets.append(round(frame.targets[0].price if frame.targets else 0.0, 2))
        if direction == -1 and avwap_lower > 0:
            targets.append(round(avwap_lower, 2))
        elif direction == 1 and avwap_upper > 0:
            targets.append(round(avwap_upper, 2))
        elif len(frame.targets) > 1:
            targets.append(round(frame.targets[1].price, 2))

        # Confidence: velocity is now a hard gate, not a soft weight.
        # 3-factor composite rebalanced: sigma_magnitude, hurst_quality, vol_stability.
        sigma_magnitude = min(1.0, (abs(sigma) - sigma_min) / max(1e-9, sigma_min))
        hurst_mr_quality = float(features.get("hurst_mr_quality", 1.0 - hurst))
        hurst_quality = min(1.0, max(0.0, hurst_mr_quality))
        vol_regime = float(features.get("vol_regime", 0.5))
        vol_stability = 1.0 - abs(vol_regime - 0.5) * 2.0

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
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
        )
        ctx = capture_signal_features(features, direction, "mean_reversion", signal["confidence"])
        signal["features_snapshot"] = ctx
        signal["context_features"] = ctx
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AnchoredVWAPReversionPlugin()
