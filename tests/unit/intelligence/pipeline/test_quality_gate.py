"""Unit tests for apply_quality_gate pure function."""
from __future__ import annotations


from src.intelligence.pipeline.quality_gate import apply_quality_gate


def make_signal(confidence=0.8, plugin="trad_TrendFollowing", direction=1, regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": direction,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


def test_applies_min_hurst_entropy_times_drift():
    """min(hurst, entropy) * drift applied to confidence."""
    sig = make_signal(confidence=0.8)
    thresholds = {"hurst_quality": 0.9, "entropy_quality": 0.85, "drift_penalty": 0.9}
    result = apply_quality_gate([sig], thresholds)
    expected_conf = round(0.8 * 0.85 * 0.9, 4)
    expected_score = round(0.85 * 0.9, 4)
    assert result[0]["confidence"] == expected_conf
    assert result[0]["quality_score"] == expected_score


def test_defaults_to_one_on_missing_thresholds():
    """Empty thresholds → confidence unchanged, quality_score=1.0."""
    sig = make_signal(confidence=0.8)
    result = apply_quality_gate([sig], {})
    assert result[0]["confidence"] == 0.8
    assert result[0]["quality_score"] == 1.0


def test_does_not_mutate_input():
    """Original signal dict must not be modified."""
    sig = make_signal(confidence=0.8)
    original_conf = sig["confidence"]
    apply_quality_gate([sig], {"hurst_quality": 0.5, "entropy_quality": 0.5, "drift_penalty": 0.5})
    assert sig["confidence"] == original_conf


def test_returns_all_signals():
    """Three inputs → three outputs (gate does not drop)."""
    signals = [make_signal(confidence=0.5), make_signal(confidence=0.6), make_signal(confidence=0.7)]
    result = apply_quality_gate(signals, {"hurst_quality": 0.9, "entropy_quality": 0.95, "drift_penalty": 1.0})
    assert len(result) == 3


def test_hurst_lower_than_entropy_uses_hurst():
    """min() picks hurst when hurst < entropy."""
    sig = make_signal(confidence=1.0)
    thresholds = {"hurst_quality": 0.5, "entropy_quality": 0.9, "drift_penalty": 1.0}
    result = apply_quality_gate([sig], thresholds)
    assert result[0]["quality_score"] == round(0.5 * 1.0, 4)
