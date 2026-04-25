"""Calibrator pipeline stage — pure function.

Applies isotonic regression calibration curves per (plugin_name, timeframe).
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder


async def apply_calibration(
    signals: list[dict],
    cal_curves: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]],
    tf: str,
    symbol: str = "*",
    recorder: TransformRecorder | None = None,
) -> list[dict]:
    """Apply isotonic calibration curves to all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each must have "confidence" and "setup_plugin".
    cal_curves:
        Dict keyed by (plugin_name, tf, symbol) → (breakpoints, values) numpy arrays.
        Loaded from DB by the caller. Empty dict → passthrough for all signals.
        symbol='*' is the global sentinel (cross-instrument aggregate).
    tf:
        Current timeframe string (e.g. "1m").
    symbol:
        Instrument symbol for per-symbol lookup (e.g. "ES", "NQ").
        Falls back to global '*' sentinel. Default '*' for backward compatibility.
    recorder:
        Optional TransformRecorder. When provided, emits one isotonic record per
        signal (only when raw_confidence > 0). When None, behavior is unchanged.

    Lookup hierarchy:
        1. (plugin_name, tf, symbol)  -- symbol-specific
        2. (plugin_name, tf, '*')     -- global sentinel
        3. passthrough (confidence unchanged)

    Returns
    -------
    list[dict]
        Copies of input signals with updated "confidence" and "calibrated_confidence" set.
        When no curve is available, confidence passes through unchanged.
        Input dicts are never mutated.
    """
    result = []

    for sig in signals:
        s = dict(sig)
        raw_confidence = float(s.get("confidence", 0.0))
        plugin_name = s.get("setup_plugin", "unknown")

        _key_specific = (plugin_name, tf, symbol)
        _key_global = (plugin_name, tf, "*")
        curve = cal_curves.get(_key_specific, cal_curves.get(_key_global))

        if curve is None:
            # No calibration curve — pass through unchanged
            calibrated = raw_confidence
        else:
            breakpoints, values = curve
            calibrated = round(float(np.interp(raw_confidence, breakpoints, values)), 4)

        s["confidence"] = calibrated
        s["calibrated_confidence"] = calibrated

        if recorder is not None and s.get("signal_id"):
            raw = float(s.get("raw_confidence", raw_confidence) or raw_confidence or 0.0)
            new_conf = float(calibrated)
            if raw > 0:
                ratio = new_conf / raw
                seg = f"{plugin_name}.{tf}"
                await recorder.record(
                    signal_id=s["signal_id"],
                    transform_id="isotonic",
                    dag_order=4,
                    multiplier=ratio,
                    segment_key=seg,
                    metadata={"raw_confidence": raw, "calibrated_confidence": new_conf},
                )

        result.append(s)

    return result
