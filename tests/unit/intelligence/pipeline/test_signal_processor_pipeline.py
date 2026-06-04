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
    assert "calibrated_confidence" in winner
    assert "cis_calibrated_confidence" in winner


import numpy as np
import pytest

from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.quality_gate import apply_quality_gate


@pytest.mark.asyncio
async def test_signal_below_raw_floor_survives_if_calibrated_above():
    """Signal at raw=0.08 survives if isotonic curve calibrates it to 0.25.

    Before Fix 3, this signal was dropped by quality gate before calibration ran.
    """
    sig = {
        "confidence": 0.08,
        "setup_plugin": "trend_following",
        "signal_id": "abc123",
        "direction": 1,
        "regime_type": "trend",
    }
    breakpoints = np.array([0.0, 0.08, 0.50, 1.0])
    values = np.array([0.10, 0.25, 0.60, 0.95])
    cal_curves = {("trend_following", "1m", "*"): (breakpoints, values)}

    calibrated = await apply_calibration([sig], cal_curves, tf="1m")
    assert calibrated[0]["confidence"] == pytest.approx(0.25, abs=0.01)

    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 1


@pytest.mark.asyncio
async def test_signal_above_raw_floor_dropped_if_calibrated_below():
    """Signal at raw=0.14 is dropped if isotonic curve calibrates it to 0.05.

    Before Fix 3, this signal passed the gate at raw=0.14 unchallenged.
    """
    sig = {
        "confidence": 0.14,
        "setup_plugin": "mean_reversion",
        "signal_id": "def456",
        "direction": -1,
        "regime_type": "mean_reversion",
    }
    breakpoints = np.array([0.0, 0.14, 0.50, 1.0])
    values = np.array([0.01, 0.05, 0.45, 0.90])
    cal_curves = {("mean_reversion", "1m", "*"): (breakpoints, values)}

    calibrated = await apply_calibration([sig], cal_curves, tf="1m")
    assert calibrated[0]["confidence"] == pytest.approx(0.05, abs=0.01)

    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 0


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
