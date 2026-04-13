"""Calibrator pipeline stage — pure function.

Applies isotonic regression calibration curves per (plugin_name, timeframe).
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

import numpy as np


def apply_calibration(
    signals: list[dict],
    cal_curves: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]],
    tf: str,
    symbol: str = "*",
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

        curve = cal_curves.get((plugin_name, tf, symbol)) or cal_curves.get((plugin_name, tf, "*"))

        if curve is None:
            # No calibration curve — pass through unchanged
            calibrated = raw_confidence
        else:
            breakpoints, values = curve
            calibrated = round(float(np.interp(raw_confidence, breakpoints, values)), 4)

        s["confidence"] = calibrated
        s["calibrated_confidence"] = calibrated
        result.append(s)

    return result
