"""Quality Gate pipeline stage — pure function.

Applies Hurst×Entropy quality multiplier and KS drift penalty to signal confidence.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations


def apply_quality_gate(
    signals: list[dict],
    thresholds: dict,
) -> list[dict]:
    """Apply quality multipliers to all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each must have a "confidence" key.
    thresholds:
        Dict with optional keys:
        - "hurst_quality" (float, default 1.0)
        - "entropy_quality" (float, default 1.0)
        - "drift_penalty" (float, default 1.0)

    Returns
    -------
    list[dict]
        Copies of input signals with updated "confidence" and "quality_score".
        Input dicts are never mutated.
    """
    hurst_q = float(thresholds.get("hurst_quality", 1.0))
    entropy_q = float(thresholds.get("entropy_quality", 1.0))
    drift_penalty = float(thresholds.get("drift_penalty", 1.0))

    # Use min() not product — hurst and entropy are correlated measures
    quality_multiplier = min(hurst_q, entropy_q)
    quality_score = round(quality_multiplier * drift_penalty, 4)

    result = []
    for sig in signals:
        s = dict(sig)
        before = float(s.get("confidence", 0.0))
        s["confidence"] = round(before * quality_multiplier * drift_penalty, 4)
        s["quality_score"] = quality_score
        result.append(s)

    return result
