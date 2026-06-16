"""Microstructure utility functions for I7 trading plugins.

Shared spike detection logic for OFI and CVD signals.
Preserves signal identity (Renaissance principle) while eliminating duplication.
"""

from __future__ import annotations

from typing import Any

from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
    rel_volume_score,
)
from .plugin_utils import no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade

_SPIKE_THRESHOLD: float = 2.0

_config_service: Any | None = None


def set_config_service(config: Any) -> None:
    global _config_service
    _config_service = config


def get_spike_threshold() -> float:
    if _config_service is not None:
        return _config_service.get_sync("threshold.microstructure.spike_z", _SPIKE_THRESHOLD)
    return _SPIKE_THRESHOLD


def detect_spike_signal(
    frames: dict[str, Any],
    spike_feature_key: str,
    signal_name_prefix: str,
    min_lookback: int = 20,
    setup_plugin: str = "",
    regime_type: str = "any",
) -> dict[str, Any]:
    """Detect microstructure spike signals (OFI or CVD).

    Shared logic for OFISpike and CVDSpike plugins. Both detect when a
    single-bar microstructure measure exceeds 2 sigma above rolling mean.

    Args:
        frames: Frame dict with 'main' (DataFrame) and 'features' (dict)
        spike_feature_key: Feature key to check ("ofi_spike_z" or "cvd_spike_z")
        signal_name_prefix: Prefix for signal_type ("ofi_spike" or "cvd_spike")
        min_lookback: Minimum bars required (default 20)
        setup_plugin: Plugin name for signal attribution

    Returns:
        Signal dict with standard I7 outputs, or empty dict if no signal

    Renaissance principles:
    - Instrument everything: z-score magnitude logged in supporting_factors
    - Segment relentlessly: fires in any regime (microstructure is regime-agnostic)
    - Degrade gracefully: missing spike_z → no signal (don't estimate)
    """
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
    if df is None or len(df) < min_lookback:
        return no_signal()

    spike_z = features.get(spike_feature_key)
    if spike_z is None:
        return no_signal()

    spike_z = float(spike_z)
    abs_spike_z = abs(spike_z)
    spike_threshold = get_spike_threshold()
    if abs_spike_z <= spike_threshold:
        return no_signal()

    # Gate 1: regime gate (spike signals are regime_type="any" — use hmm_trending_weight)
    if hmm_trending_weight(features) < get_min_regime_weight():
        return no_signal()

    atr = get_atr_with_floor_from_frames(frames)
    if atr is None:
        return no_signal()

    close = df["close"].to_numpy(dtype=float)
    entry = float(close[-1])

    direction = 1 if spike_z > 0 else -1

    # 3-factor intrinsic confidence composite — ctf_factor removed (ECL annotation, Phase 123)
    z_score_score = clamp01((abs_spike_z - spike_threshold) / 3.0)

    volume_score = rel_volume_score(features)

    price_return_z = features.get("price_return_z")
    if price_return_z is not None:
        persistence_score = clamp01(abs_spike_z / max(1.0, abs(float(price_return_z))) - 1.0)
    else:
        persistence_score = 0.3

    # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
    factor_scores = {
        "z_score_score": round(z_score_score, 4),
        "volume_score": round(volume_score, 4),
        "persistence_score": round(persistence_score, 4),
    }

    # Weights sum to 1.0: 0.50/0.30/0.20 (ctf_factor removed, weight redistributed)
    raw = 0.50 * z_score_score + 0.30 * volume_score + 0.20 * persistence_score
    confidence = compose_confidence(raw)

    sig_type = signal_type_for_direction(signal_name_prefix, direction)
    tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=regime_type)
    if not tf.viable:
        return no_signal()

    hmm_regime = features.get("hmm_regime")
    regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
    supporting: list[str] = [
        f"{spike_feature_key}={spike_z:.3f}",
    ]

    # Exhaustion not applicable — spike signals are regime-independent;
    # Phase 49 will learn gate behavior from shadow data
    signal = make_signal_from_frame(
        tf,
        symbol=frames.get("symbol", ""),
        timeframe=features.get("timeframe", ""),
        timestamp=features.get("timestamp", ""),
        signal_type=sig_type,
        setup_plugin=setup_plugin,
        direction=direction,
        confidence=confidence,
        regime_context=regime_context,
        supporting_factors=supporting,
        factor_scores=factor_scores,
    )
    return signal
