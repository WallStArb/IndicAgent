"""Regime Gate pipeline stage — pure function.

Applies HMM regime compatibility check to signals.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from src.intelligence.trading.aggregator import _REGIME_MAP
from src.observability.metrics import REGIME_SOFT_GATE_SIGNALS_TOTAL

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder

# Minimum multiplier applied at the lower edge of the soft band
# (prob == REGIME_PROB_MIN → multiplier == SOFT_BAND_FLOOR).
SOFT_BAND_FLOOR: float = 0.5


def _entropy_multiplier(
    prob: float,
    entropy: float | None,
    prob_min: float,
    prob_soft_max: float,
) -> float:
    """Compute soft-band confidence multiplier from regime probability and entropy.

    Parameters
    ----------
    prob:
        HMM dominant-state probability for this bar (in [prob_min, prob_soft_max)).
    entropy:
        Shannon entropy of the 3-state HMM distribution (from hmm_regime_entropy).
        None when the HMM has not yet warmed up — skips entropy adjustment.
    prob_min:
        Lower boundary of the soft band (REGIME_PROB_MIN).
    prob_soft_max:
        Upper boundary of the soft band (REGIME_PROB_SOFT_MAX).

    Returns
    -------
    float
        Multiplier in [SOFT_BAND_FLOOR, 1.0].  Applied to calibrated_confidence.

    Formula
    -------
    t = clamp((prob - prob_min) / (prob_soft_max - prob_min), 0, 1)
    base = SOFT_BAND_FLOOR + (1 - SOFT_BAND_FLOOR) * t

    If entropy is known, apply additional attenuation proportional to normalized
    entropy (max entropy for 3 states = log2(3)).  Uniform distribution →
    entropy_factor = 0.5; zero-entropy (certain) → entropy_factor = 1.0.
    """
    # Linear interpolation parameter — protected against zero-width band
    t = (prob - prob_min) / max(1e-9, prob_soft_max - prob_min)
    t = max(0.0, min(1.0, t))

    # Base multiplier: SOFT_BAND_FLOOR at lower edge, 1.0 at upper edge
    multiplier = SOFT_BAND_FLOOR + (1.0 - SOFT_BAND_FLOOR) * t

    # Entropy-weighted attenuation: uniform 3-state → max_entropy = log2(3)
    # entropy_factor in [0.5, 1.0]: 0.5 when max-entropy, 1.0 when zero-entropy
    if entropy is not None:
        max_entropy = math.log2(3)
        entropy_factor = max(0.5, 1.0 - 0.5 * (entropy / max_entropy))
        multiplier *= entropy_factor

    return multiplier


async def apply_regime_gate(
    signals: list[dict],
    regime_data: dict | None,
    *,
    prob_min: float = 0.30,
    prob_soft_max: float = 0.55,
    dur_min: int = 1,
    tf: str | None = None,
    recorder: TransformRecorder | None = None,
) -> list[dict]:
    """Apply regime gating to all signals.

    Three-band logic (Phase 82 D-04):
    1. prob < prob_min:                         suppress (regime_eligible=False)
    2. prob_min <= prob < prob_soft_max:         soft band — eligible but
                                                 calibrated_confidence attenuated
    3. prob >= prob_soft_max:                    full confidence (unchanged)

    Parameters
    ----------
    signals:
        List of signal dicts. Each may have a "regime_type" key.
    regime_data:
        Dict with HMM regime info, or None for graceful degradation.
        Expected keys: "hmm_regime", "hmm_regime_prob", "hmm_regime_duration".
        Optional key: "hmm_regime_entropy" (float) — used by soft-band attenuation.
    prob_min:
        Minimum HMM regime probability to trust the regime label.
        Default 0.30 is a safety floor (D-02, SHADOW-01) — not a quality filter.
        Set via REGIME_PROB_MIN env var in Settings.
    prob_soft_max:
        Upper boundary of the soft band.  Signals with prob >= this value receive
        full confidence (unchanged).  Default 0.55.
        Set via REGIME_PROB_SOFT_MAX env var in Settings.
    dur_min:
        Minimum number of bars the regime must have been stable.
        Default 1 is a safety floor (D-02, SHADOW-01).
        Set via REGIME_DUR_MIN env var in Settings.
    tf:
        Current timeframe string. Unused directly but accepted for interface
        consistency with other pipeline stages.
    recorder:
        Optional TransformRecorder. When provided, emits one regime_gate record
        per signal. When None, behavior is unchanged.

    Returns
    -------
    list[dict]
        Copies of input signals with "regime_eligible" and "suppression_reason" set.
        Soft-band signals also have "calibrated_confidence" attenuated.
        Input dicts are never mutated.
    """
    result = []

    if regime_data is None:
        # No regime data → pass all through (graceful degradation)
        for sig in signals:
            s = dict(sig)
            s["regime_eligible"] = True
            s["suppression_reason"] = None

            if recorder is not None and s.get("signal_id"):
                seg = str(s.get("regime_type", "any"))
                await recorder.record(
                    signal_id=s["signal_id"],
                    transform_id="regime_gate",
                    dag_order=2,
                    multiplier=1.0,
                    segment_key=seg,
                    metadata={
                        "hmm_regime": None,
                        "hmm_regime_prob": None,
                        "suppression_reason": None,
                    },
                )

            result.append(s)
        return result

    hmm_regime = regime_data.get("hmm_regime")
    hmm_regime_prob = float(regime_data.get("hmm_regime_prob", 0.0))
    hmm_regime_duration = int(regime_data.get("hmm_regime_duration", 0))
    hmm_regime_entropy = regime_data.get("hmm_regime_entropy")  # float | None

    for sig in signals:
        s = dict(sig)
        plugin_regime_type = s.get("regime_type", "any")
        allowed = _REGIME_MAP.get(plugin_regime_type, [0, 1, 2])

        regime_eligible = True
        suppression_reason = None
        gate_multiplier = 1.0  # multiplier emitted to TransformRecorder

        if hmm_regime_prob < prob_min:
            # Band 1: suppress
            regime_eligible = False
            suppression_reason = "regime_prob"
            REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="suppressed").inc()
        elif hmm_regime_prob < prob_soft_max:
            # Band 2: soft — eligible but attenuated
            multiplier = _entropy_multiplier(
                hmm_regime_prob,
                hmm_regime_entropy,
                prob_min,
                prob_soft_max,
            )
            base_conf = s.get("calibrated_confidence", s.get("confidence", 0.5))
            s["calibrated_confidence"] = base_conf * multiplier
            gate_multiplier = multiplier
            REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="soft").inc()
        else:
            # Band 3: full confidence
            REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="full").inc()

        # Downstream duration / regime-type checks run only when still eligible
        if regime_eligible:
            if hmm_regime_duration < dur_min:
                regime_eligible = False
                suppression_reason = "regime_duration"
            elif hmm_regime is not None and int(hmm_regime) not in allowed:
                regime_eligible = False
                suppression_reason = "regime_type"

        s["regime_eligible"] = regime_eligible
        s["suppression_reason"] = suppression_reason

        if recorder is not None and s.get("signal_id"):
            seg = str(s.get("regime_type", "any"))
            await recorder.record(
                signal_id=s["signal_id"],
                transform_id="regime_gate",
                dag_order=2,
                multiplier=gate_multiplier if regime_eligible else 0.0,
                segment_key=seg,
                metadata={
                    "hmm_regime": hmm_regime,
                    "hmm_regime_prob": hmm_regime_prob,
                    "suppression_reason": suppression_reason,
                },
            )

        result.append(s)

    return result
