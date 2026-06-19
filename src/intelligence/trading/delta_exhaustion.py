"""trad_DeltaExhaustion — I7 mean-reversion setup consuming CVD I1 features.

Fires when a large CVD spike occurs but price fails to follow through.
This is the "exhaustion" pattern: informed buyers/sellers pushed volume but price
didn't respond, suggesting the aggressive side is exhausted and price will reverse.

Renaissance principles:
- Segment relentlessly: requires both CVD spike AND price failure (dual gate)
- Instrument everything: price_follow_ratio, cvd_spike_z all logged
- Earn the right through proof: price must fail to follow (< 0.3 ATR move)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    _validate_weights_sum,
    clamp01,
    compose_confidence,
    get_min_regime_weight,
)
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_SPIKE_Z_THRESHOLD: float = 1.5  # lower than OFI/CVD spike (1.5 vs 2.0 — captures more cases)
_PRICE_FOLLOW_THRESHOLD: float = 0.3  # price must move < 0.3 ATR for exhaustion
_W_CVD_Z: float = 0.35
_W_PRICE_FAIL: float = 0.30
_W_HMM_RANGING: float = 0.25
_W_PERSISTENCE: float = 0.10


@dataclass
class DeltaExhaustionPlugin:
    """Mean-reversion setup: large CVD spike but price fails to follow through.

    Gates:
    - abs(cvd_spike_z) > 1.5 (significant CVD spike)
    - abs(price_change) < 0.3 * atr (price fails to follow CVD direction)

    Direction: opposite of CVD spike direction (exhaustion → reversal)
    Confidence: 4-factor intrinsic composite via compose_confidence()
    """

    name: str = "trad_DeltaExhaustion"
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
    capability_tags: frozenset[str] = frozenset({"trading", "exhaustion", "cvd", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    _config_service: Any = field(default=None, compare=False, repr=False)

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
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
        if df is None or len(df) < self.min_lookback:
            return no_signal()

        cvd_spike_z = features.get("cvd_spike_z")
        if cvd_spike_z is None:
            return no_signal()

        cvd_spike_z = float(cvd_spike_z)

        cfg = self._config_service
        spike_z_threshold = (
            cfg.get_sync("threshold.delta_exhaustion.spike_z", _SPIKE_Z_THRESHOLD)
            if cfg
            else _SPIKE_Z_THRESHOLD
        )
        price_follow_threshold = (
            cfg.get_sync("threshold.delta_exhaustion.price_follow_atr", _PRICE_FOLLOW_THRESHOLD)
            if cfg
            else _PRICE_FOLLOW_THRESHOLD
        )
        w_cvd_z = cfg.get_sync("weights.delta_exhaustion.cvd_z", _W_CVD_Z) if cfg else _W_CVD_Z
        w_price_fail = (
            cfg.get_sync("weights.delta_exhaustion.price_fail", _W_PRICE_FAIL)
            if cfg
            else _W_PRICE_FAIL
        )
        w_hmm_ranging = (
            cfg.get_sync("weights.delta_exhaustion.hmm_ranging", _W_HMM_RANGING)
            if cfg
            else _W_HMM_RANGING
        )
        w_persistence = (
            cfg.get_sync("weights.delta_exhaustion.persistence", _W_PERSISTENCE)
            if cfg
            else _W_PERSISTENCE
        )
        _validate_weights_sum(
            {
                "cvd_z": w_cvd_z,
                "price_fail": w_price_fail,
                "hmm_ranging": w_hmm_ranging,
                "persistence": w_persistence,
            },
            "trad_DeltaExhaustion",
        )
        if abs(cvd_spike_z) <= spike_z_threshold:
            return no_signal()

        # ── Dual gate (before ATR / OHLCV access) ────────────────────────────
        # Gate 1: mean_reversion regime gate — ranging probability >= threshold
        if hmm_regime_weight(features, "ranging") < get_min_regime_weight():
            return no_signal()

        # ── ATR and OHLCV access (after dual gate) ───────────────────────────
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        if atr <= 0:
            return no_signal()

        # Price follow-through: compare current close to previous close
        close = df["close"].to_numpy(dtype=float)
        if len(close) < 2:
            return no_signal()

        entry = float(close[-1])
        prev_close = float(close[-2])
        price_change = abs(entry - prev_close)
        price_follow_ratio = price_change / atr

        # CVD direction: positive spike = buying pressure
        cvd_direction = 1 if cvd_spike_z > 0 else -1

        # Price failed to follow: price change is less than threshold
        if price_follow_ratio >= price_follow_threshold:
            return no_signal()

        # Exhaustion: opposite of CVD direction
        direction = -cvd_direction

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        # cvd_z_score: spike magnitude above threshold
        cvd_z_score = clamp01((abs(cvd_spike_z) - spike_z_threshold) / 3.0)

        # price_fail_score: how completely price failed to follow (1.0 = zero follow-through)
        price_fail_score = clamp01(1.0 - price_follow_ratio / price_follow_threshold)

        # hmm_mean_reversion_score: regime alignment magnitude as quality signal
        # This is the regime ALIGNMENT factor — NOT exhaustion boost/guard (D-09 exempt)
        hmm_mean_reversion_score = clamp01(
            (hmm_regime_weight(features, "ranging") - get_min_regime_weight())
            / (1.0 - get_min_regime_weight())
        )

        # persistence_score proxy: how persistent the CVD spike magnitude was
        # (cvd_spike_z is already in scope from the gate above)
        persistence_score = clamp01(abs(cvd_spike_z) / 3.0)

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "cvd_z_score": round(cvd_z_score, 4),
            "price_fail_score": round(price_fail_score, 4),
            "hmm_mean_reversion_score": round(hmm_mean_reversion_score, 4),
            "persistence_score": round(persistence_score, 4),
        }

        raw_conf = (
            w_cvd_z * cvd_z_score
            + w_price_fail * price_fail_score
            + w_hmm_ranging * hmm_mean_reversion_score
            + w_persistence * persistence_score
        )
        confidence = compose_confidence(raw_conf)

        sig_type = signal_type_for_direction("delta_exhaustion", direction)
        tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        hmm_regime = features.get("hmm_regime")
        regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

        supporting: list[str] = [
            f"cvd_spike_z={cvd_spike_z:.3f}",
            f"price_follow_ratio={price_follow_ratio:.3f}",
            f"atr={atr:.2f}",
        ]

        # exempt from exhaustion shadow: this plugin IS the exhaustion detector (D-09)
        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin="trad_DeltaExhaustion",
            direction=direction,
            confidence=confidence,
            regime_context=regime_context,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = DeltaExhaustionPlugin()
