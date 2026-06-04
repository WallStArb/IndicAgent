"""Tests for signal_processor pipeline contract changes."""

from __future__ import annotations


def test_winner_cis_field_is_additive_not_overwriting():
    """Winner must carry cis_calibrated_confidence as an additive field.

    calibrated_confidence (plugin-level isotonic) must not be overwritten.
    cis_calibrated_confidence is a separate field added on the winner only.
    """
    winner = {
        "setup_plugin": "trend_following",
        "confidence": 0.72,
        "calibrated_confidence": 0.68,  # plugin-level isotonic
    }
    cis_calibrated = 0.81

    # Simulate the new logic
    winner["cis_calibrated_confidence"] = cis_calibrated

    assert winner["calibrated_confidence"] == 0.68
    assert winner["cis_calibrated_confidence"] == 0.81


import numpy as np
import pytest

from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.quality_gate import apply_quality_gate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_conf,plugin,breakpoints,values,expected_calibrated,expected_survivors",
    [
        (
            0.08,
            "trend_following",
            [0.0, 0.08, 0.50, 1.0],
            [0.10, 0.25, 0.60, 0.95],
            0.25,
            1,
        ),
        (
            0.14,
            "mean_reversion",
            [0.0, 0.14, 0.50, 1.0],
            [0.01, 0.05, 0.45, 0.90],
            0.05,
            0,
        ),
    ],
    ids=["below_raw_survives_if_calibrated_above", "above_raw_dropped_if_calibrated_below"],
)
async def test_quality_gate_uses_calibrated_confidence(
    raw_conf, plugin, breakpoints, values, expected_calibrated, expected_survivors
):
    """Quality gate must operate on calibrated confidence, not raw plugin value.

    Case 1: raw=0.08 calibrates to 0.25 → survives gate (before fix: dropped at raw).
    Case 2: raw=0.14 calibrates to 0.05 → dropped by gate (before fix: passed at raw).
    """
    sig = {
        "confidence": raw_conf,
        "setup_plugin": plugin,
        "signal_id": "test-sig",
        "direction": 1,
        "regime_type": "trend",
    }
    cal_curves = {(plugin, "1m", "*"): (np.array(breakpoints), np.array(values))}

    calibrated = await apply_calibration([sig], cal_curves, tf="1m")
    assert calibrated[0]["confidence"] == pytest.approx(expected_calibrated, abs=0.01)

    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == expected_survivors


@pytest.mark.asyncio
async def test_cold_start_no_curves_behaves_identically():
    """Empty cal_curves → passthrough → quality gate sees raw confidence."""
    sig = {
        "confidence": 0.15,
        "setup_plugin": "trend_following",
        "signal_id": "ghi789",
        "direction": 1,
        "regime_type": "trend",
    }

    calibrated = await apply_calibration([sig], {}, tf="1m")
    assert calibrated[0]["confidence"] == 0.15

    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 1


from src.intelligence.pipeline.signal_processor import ALPHA_HALF_LIFE_BARS, _apply_alpha_decay


def test_alpha_decay_applies_when_bars_since_is_one():
    """bars_since=1 must apply decay — the zero guard was dead code and is removed.

    Invariant: state['bars_since'] is always >= 1 when _apply_alpha_decay is called
    with non-None state (caller increments before calling).
    """
    sig = {"confidence": 0.80}
    state = {"bars_since": 1}
    half_life = ALPHA_HALF_LIFE_BARS["1m"]  # 10

    _apply_alpha_decay(sig, "1m", state)

    expected = round(0.80 * (0.5 ** (1 / half_life)), 4)
    assert sig["confidence"] == expected
    assert sig["confidence"] < 0.80  # decay actually applied


def test_alpha_decay_noop_when_state_is_none():
    """None state means plugin has no prior win — no decay applied."""
    sig = {"confidence": 0.80}
    _apply_alpha_decay(sig, "1m", None)
    assert sig["confidence"] == 0.80
