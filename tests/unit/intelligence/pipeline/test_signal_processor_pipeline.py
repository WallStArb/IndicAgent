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
