"""Quality Gate pipeline stage — pure function.

Applies Hurst×Entropy quality multiplier and KS drift penalty to signal confidence.
Also applies an empirical quality floor (SIGNAL_MIN_PUBLISHABLE_CONFIDENCE) to
reject signals below the minimum confidence threshold.

Quality floor bootstrap (DAG-compliant, D-05):
  The empirical floor is derived by a standalone oneshot helper:
    services/quality_floor_bootstrap.py
  That script queries signal_ledger and writes a single float to
  .pipeline_quality_floor (project root). quality_gate reads it at pipeline
  startup via load_quality_floor(). The pipeline daemon never touches the DB
  directly (DAG Invariant #3 preserved).

No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from opentelemetry import metrics as otel_metrics

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder

_logger = logging.getLogger(__name__)

# Default quality floor path — written by services/quality_floor_bootstrap.py
_DEFAULT_FLOOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", ".pipeline_quality_floor"
)

# OTel counter for floor rejections — created once at module import.
# Counter: signals rejected because confidence < quality floor.
_meter = otel_metrics.get_meter("indicagent")
QUALITY_FLOOR_REJECTIONS_TOTAL = _meter.create_counter(
    name="intelligence_pipeline_quality_floor_rejections_total",
    description="Signals rejected below empirical quality floor",
    unit="1",
)

# Module-level constant: configures SIGNAL_MIN_PUBLISHABLE_CONFIDENCE default
SIGNAL_MIN_PUBLISHABLE_CONFIDENCE: float = 0.12


def load_quality_floor(path: str | None = None, default: float = 0.12) -> float:
    """Load empirical quality floor from file written by quality_floor_bootstrap.py.

    Parameters
    ----------
    path:
        Path to the floor file. Defaults to .pipeline_quality_floor in the
        project root. Override for testing or alternate deployment paths.
    default:
        Value to return when file is absent or unreadable. Defaults to 0.12
        (D-05 spec default).

    Returns
    -------
    float
        The empirical floor value. Returns default on any error.
    """
    file_path = path or _DEFAULT_FLOOR_PATH
    try:
        with open(file_path) as f:
            value = float(f.read().strip())
        _logger.info("quality_gate: loaded floor=%.4f from %s", value, file_path)
        return value
    except FileNotFoundError:
        _logger.warning(
            "quality_gate: floor file not found at %s; using default %.4f",
            file_path,
            default,
        )
        return default
    except Exception as error:  # noqa: BLE001
        _logger.warning(
            "quality_gate: failed to read floor from %s: %s; using default %.4f",
            file_path,
            error,
            default,
        )
        return default


async def apply_quality_gate(
    signals: list[dict],
    thresholds: dict,
    *,
    tf: str | None = None,
    recorder: TransformRecorder | None = None,
    min_confidence: float = 0.0,
) -> list[dict]:
    """Apply quality multipliers and empirical floor to all signals.

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
        is provided and for floor rejection labeling.
    recorder:
        Optional TransformRecorder. When provided, emits one hurst_quality record
        and one drift_penalty record per signal. When None, behavior is unchanged.
    min_confidence:
        Minimum confidence after multipliers applied. Signals below this floor are
        dropped and counted by intelligence_pipeline_quality_floor_rejections_total.
        Default 0.0 (no floor — backward compatible). Pass
        settings.SIGNAL_MIN_PUBLISHABLE_CONFIDENCE for the empirical floor.

    Returns
    -------
    list[dict]
        Copies of input signals with updated "confidence" and "quality_score".
        Signals below min_confidence are excluded.
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

        # Empirical quality floor: drop signals below min_confidence
        if min_confidence > 0.0 and s["confidence"] < min_confidence:
            QUALITY_FLOOR_REJECTIONS_TOTAL.add(1, {"tf": tf or "unknown"})
            continue

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
