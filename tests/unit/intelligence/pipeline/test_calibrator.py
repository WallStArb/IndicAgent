"""Unit tests for apply_calibration pure function."""
from __future__ import annotations

import numpy as np

from src.intelligence.pipeline.calibrator import apply_calibration


def make_signal(confidence=0.6, plugin="trad_X", regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": 1,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


def test_applies_isotonic_curve():
    """Known curve → np.interp result returned."""
    bp = np.array([0.0, 0.5, 1.0])
    vals = np.array([0.0, 0.6, 1.0])
    curves = {("trad_X", "1m"): (bp, vals)}
    sig = make_signal(confidence=0.5, plugin="trad_X")
    result = apply_calibration([sig], curves, "1m")
    expected = round(float(np.interp(0.5, bp, vals)), 4)
    assert result[0]["confidence"] == expected
    assert result[0]["calibrated_confidence"] == expected


def test_no_curve_passthrough():
    """No curve for plugin → confidence unchanged."""
    sig = make_signal(confidence=0.7, plugin="trad_Unknown")
    result = apply_calibration([sig], {}, "1m")
    assert result[0]["confidence"] == 0.7


def test_sets_calibrated_confidence_field():
    """calibrated_confidence field is always set after call."""
    bp = np.array([0.0, 0.5, 1.0])
    vals = np.array([0.0, 0.65, 1.0])
    curves = {("trad_X", "1m"): (bp, vals)}
    sig = make_signal(confidence=0.4, plugin="trad_X")
    result = apply_calibration([sig], curves, "1m")
    assert "calibrated_confidence" in result[0]
    assert result[0]["calibrated_confidence"] is not None


def test_does_not_mutate_input():
    """Input signal dicts are not mutated."""
    sig = make_signal(confidence=0.6, plugin="trad_X")
    bp = np.array([0.0, 0.5, 1.0])
    vals = np.array([0.0, 0.7, 1.0])
    curves = {("trad_X", "1m"): (bp, vals)}
    original_conf = sig["confidence"]
    apply_calibration([sig], curves, "1m")
    assert sig["confidence"] == original_conf


def test_no_curve_passthrough_also_sets_calibrated_field():
    """No curve → calibrated_confidence equals input confidence."""
    sig = make_signal(confidence=0.55, plugin="trad_Unknown")
    result = apply_calibration([sig], {}, "1m")
    assert result[0]["calibrated_confidence"] == 0.55
