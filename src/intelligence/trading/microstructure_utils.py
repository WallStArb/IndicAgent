"""Microstructure utility functions for I7 trading plugins.

Shared spike detection logic for OFI and CVD signals.
Preserves signal identity (Renaissance principle) while eliminating duplication.
"""

from __future__ import annotations

from typing import Any

from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .trade_framer import frame_trade

_SPIKE_THRESHOLD: float = 2.0


def detect_spike_signal(
    frames: dict[str, Any],
    spike_feature_key: str,
    signal_name_prefix: str,
    min_lookback: int = 20,
) -> dict[str, Any]:
    """Detect microstructure spike signals (OFI or CVD).

    Shared logic for OFISpike and CVDSpike plugins. Both detect when a
    single-bar microstructure measure exceeds 2 sigma above rolling mean.

    Args:
        frames: Frame dict with 'main' (DataFrame) and 'features' (dict)
        spike_feature_key: Feature key to check ("ofi_spike_z" or "cvd_spike_z")
        signal_name_prefix: Prefix for signal_type ("ofi_spike" or "cvd_spike")
        min_lookback: Minimum bars required (default 20)

    Returns:
        Signal dict with standard I7 outputs, or empty dict if no signal

    Renaissance principles:
    - Instrument everything: z-score magnitude logged in supporting_factors
    - Segment relentlessly: fires in any regime (microstructure is regime-agnostic)
    - Degrade gracefully: missing spike_z → no signal (don't estimate)
    """
    df = frames.get("main")
    features = frames.get("features") or {}
    if df is None or len(df) < min_lookback:
        return no_signal()

    spike_z = features.get(spike_feature_key)
    if spike_z is None:
        return no_signal()

    spike_z = float(spike_z)
    if abs(spike_z) <= _SPIKE_THRESHOLD:
        return no_signal()

    atr = get_atr(features)
    if atr is None:
        return no_signal()

    close = df["close"].to_numpy(dtype=float)
    entry = float(close[-1])

    direction = 1 if spike_z > 0 else -1
    confidence = compose_confidence(0.50 + abs(spike_z) * 0.05)

    sig_type = signal_type_for_direction(signal_name_prefix, direction)
    tf = frame_trade(sig_type, direction, entry, features, atr)
    if not tf.viable:
        return no_signal()

    stop_loss = tf.stop
    targets = [t.price for t in tf.targets]

    hmm_regime = features.get("hmm_regime")
    regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"
    supporting: list[str] = [
        f"{spike_feature_key}={spike_z:.3f}",
    ]

    # Exhaustion not applicable — spike signals are regime-independent;
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
    }
    signal["_shadow"] = capture_signal_features(
        features, direction, "microstructure", signal["confidence"]
    )
    return signal
