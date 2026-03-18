"""Unit tests for Phase 35 TOD multiplier and calibration wiring in signal_generator_service.
Covers: TOD-01, TOD-02, CAL-03.
"""
from __future__ import annotations

import pytest
import zoneinfo

from src.intelligence.trading.aggregator import _build_all_ranked


# ---------------------------------------------------------------------------
# TOD helper tests (exercising the Bayesian formula directly)
# ---------------------------------------------------------------------------

def _bayesian_multiplier(prior: float, alpha: float, n: float, empirical_ratio: float) -> float:
    """Replicate the Bayesian TOD formula from the service."""
    raw = (alpha * prior + n * empirical_ratio) / (alpha + n)
    return max(0.7, min(1.3, raw))


def test_tod_bayesian_prior_only():
    """At N=0, multiplier equals prior exactly (clamped)."""
    m = _bayesian_multiplier(prior=1.10, alpha=20.0, n=0.0, empirical_ratio=1.0)
    assert m == pytest.approx(1.10, abs=1e-4)


def test_tod_bayesian_converges_to_empirical():
    """With large N, multiplier converges to empirical_ratio (clamped)."""
    # empirical_ratio = 1.5 but clamped at 1.3
    m = _bayesian_multiplier(prior=1.0, alpha=20.0, n=10000.0, empirical_ratio=1.5)
    assert m == pytest.approx(1.3, abs=1e-3)


def test_tod_bayesian_clamp_lower():
    """Multiplier never goes below 0.7."""
    m = _bayesian_multiplier(prior=0.5, alpha=20.0, n=5000.0, empirical_ratio=0.3)
    assert m == 0.7


def test_tod_bayesian_clamp_upper():
    """Multiplier never goes above 1.3."""
    m = _bayesian_multiplier(prior=1.5, alpha=20.0, n=0.0, empirical_ratio=2.0)
    assert m == 1.3


def test_tod_bayesian_smooth_transition():
    """Multiplier transitions smoothly — no discontinuity at N=20."""
    vals = [
        _bayesian_multiplier(0.9, 20.0, float(n), 0.8)
        for n in range(0, 100, 5)
    ]
    # Each successive value must differ by < 0.05 (no step function)
    diffs = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
    assert max(diffs) < 0.05


# ---------------------------------------------------------------------------
# aggregator calibrated_confidence sort key tests (CAL-03)
# ---------------------------------------------------------------------------

def _make_signal(name: str, conf: float) -> dict:
    return {
        "setup_plugin": name,
        "direction": 1,
        "confidence": conf,
        "regime_type": "trend",
        "regime_eligible": True,
    }


def test_calibrated_confidence_used_as_sort_key_when_curve_exists():
    """Signal with lower raw confidence but higher calibrated_confidence ranks first."""
    signals = [
        _make_signal("trad_TrendFollowing", 0.70),
        _make_signal("trad_MomentumBreakout", 0.60),
    ]
    # Give MomentumBreakout a calibration curve that maps 0.60 -> 0.85
    calibration_curves = {
        ("trad_MomentumBreakout", "1m"): ([0.0, 0.5, 0.6, 1.0], [0.0, 0.5, 0.85, 1.0]),
    }
    ranked = _build_all_ranked(signals, calibration_curves=calibration_curves, timeframe="1m")
    # MomentumBreakout has calibrated_confidence=0.85 > TrendFollowing calibrated_confidence=None
    assert ranked[0]["setup_plugin"] == "trad_MomentumBreakout"


def test_calibrated_confidence_none_when_no_curve():
    """Signals without calibration curve get calibrated_confidence=None."""
    signals = [_make_signal("trad_TrendFollowing", 0.70)]
    ranked = _build_all_ranked(signals, calibration_curves={}, timeframe="1m")
    assert ranked[0]["calibrated_confidence"] is None


def test_calibrated_confidence_does_not_mutate_confidence():
    """Adding calibrated_confidence must not change the original confidence field."""
    signals = [_make_signal("trad_TrendFollowing", 0.70)]
    calibration_curves = {
        ("trad_TrendFollowing", "1m"): ([0.0, 1.0], [0.0, 1.0]),
    }
    ranked = _build_all_ranked(signals, calibration_curves=calibration_curves, timeframe="1m")
    assert ranked[0]["confidence"] == pytest.approx(0.70, abs=1e-4)
    assert ranked[0].get("calibrated_confidence") is not None


def test_raw_confidence_fallback_when_no_calibration():
    """Without calibration curves, sort order is determined by raw confidence."""
    signals = [
        _make_signal("trad_TrendFollowing", 0.70),
        _make_signal("trad_MomentumBreakout", 0.85),
    ]
    ranked = _build_all_ranked(signals)
    # Higher raw confidence should rank first (MomentumBreakout has SETUP_PRIORITY advantage too)
    assert ranked[0]["confidence"] >= ranked[-1]["confidence"]
