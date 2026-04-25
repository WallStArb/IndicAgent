"""Quality Gate pipeline stage — pure function.

Applies Hurst×Entropy quality multiplier and KS drift penalty to signal confidence.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder


async def apply_quality_gate(
    signals: list[dict],
    thresholds: dict,
    *,
    tf: str | None = None,
    recorder: TransformRecorder | None = None,
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
    tf:
        Current timeframe string (e.g. "1m"). Used for segment_key when recorder
        is provided.
    recorder:
        Optional TransformRecorder. When provided, emits one hurst_quality record
        and one drift_penalty record per signal. When None, behavior is unchanged.

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

        if recorder is not None and s.get("signal_id"):
            regime_type = s.get("regime_type", "any")
            seg = f"{regime_type}.{tf or 'unknown'}"
            await recorder.record(
                signal_id=s["signal_id"],
                transform_id="hurst_quality",
                dag_order=0,
                multiplier=quality_multiplier,
                segment_key=seg,
                metadata={"hurst_q": hurst_q, "entropy_q": entropy_q},
            )
            await recorder.record(
                signal_id=s["signal_id"],
                transform_id="drift_penalty",
                dag_order=1,
                multiplier=drift_penalty,
                segment_key=seg,
                metadata={"drift_penalty": drift_penalty},
            )

        result.append(s)

    return result
