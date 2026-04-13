"""Unit tests for apply_tod_adjustment pure function."""
from __future__ import annotations

from src.intelligence.pipeline.tod_adjuster import _TOD_SESSION_PRIORS, apply_tod_adjustment


def make_signal(confidence=0.8, regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


def test_applies_db_multiplier():
    """TOD table entry multiplies confidence."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    tod_table = {("trend", "1m", 9, "*"): 1.1}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9)
    expected = round(0.8 * 1.1, 4)
    assert result[0]["confidence"] == expected
    assert result[0]["tod_multiplier"] == 1.1


def test_falls_back_to_session_priors():
    """No DB entry → falls back to _TOD_SESSION_PRIORS."""
    # ("trend", 9) has prior 1.10 in _TOD_SESSION_PRIORS
    prior = _TOD_SESSION_PRIORS.get(("trend", 9), 1.0)
    sig = make_signal(confidence=0.8, regime_type="trend")
    result = apply_tod_adjustment([sig], {}, "1m", 9)
    expected = round(0.8 * max(0.7, min(1.3, prior)), 4)
    assert result[0]["confidence"] == expected


def test_defaults_to_one_when_no_entry():
    """No DB entry and no prior → multiplier=1.0, confidence unchanged."""
    sig = make_signal(confidence=0.75, regime_type="trend")
    # hour_et=3 is not in session priors
    result = apply_tod_adjustment([sig], {}, "1m", 3)
    assert result[0]["confidence"] == 0.75
    assert result[0]["tod_multiplier"] == 1.0


def test_clamps_multiplier_high():
    """Multiplier exceeding 1.3 is clamped to 1.3."""
    sig = make_signal(confidence=0.5, regime_type="trend")
    tod_table = {("trend", "1m", 9, "*"): 2.0}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9)
    assert result[0]["tod_multiplier"] == 1.3
    assert result[0]["confidence"] == round(0.5 * 1.3, 4)


def test_clamps_multiplier_low():
    """Multiplier below 0.7 is clamped to 0.7."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    tod_table = {("trend", "1m", 9, "*"): 0.1}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9)
    assert result[0]["tod_multiplier"] == 0.7


def test_does_not_mutate_input():
    """Input signal dicts are not mutated."""
    sig = make_signal(confidence=0.8)
    original_conf = sig["confidence"]
    apply_tod_adjustment([sig], {("trend", "1m", 9, "*"): 1.2}, "1m", 9)
    assert sig["confidence"] == original_conf


# -- Symbol-keyed lookup tests (Phase 68-04) --


def test_symbol_defaults_to_star_backward_compat():
    """Calling without symbol param uses '*' global sentinel — backward-compatible."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    # Global key with '*' matches default symbol
    tod_table = {("trend", "1m", 9, "*"): 1.15}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9)
    assert result[0]["tod_multiplier"] == 1.15


def test_symbol_specific_key_tried_first():
    """When symbol='ES', the (regime_type, tf, hour_et, 'ES') key is tried first."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    tod_table = {
        ("trend", "1m", 9, "ES"): 1.2,
        ("trend", "1m", 9, "*"): 1.1,
    }
    result = apply_tod_adjustment([sig], tod_table, "1m", 9, symbol="ES")
    assert result[0]["tod_multiplier"] == 1.2


def test_symbol_falls_back_to_global_star():
    """When no symbol-specific key, falls back to (regime_type, tf, hour_et, '*')."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    tod_table = {("trend", "1m", 9, "*"): 1.1}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9, symbol="ES")
    assert result[0]["tod_multiplier"] == 1.1


def test_symbol_no_key_falls_to_session_priors():
    """When neither symbol-specific nor global '*' key exists, falls to session priors."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    # hour_et=9, regime_type="trend" has prior 1.10
    result = apply_tod_adjustment([sig], {}, "1m", 9, symbol="ES")
    assert result[0]["tod_multiplier"] == 1.10


def test_symbol_tod_multiplier_stamped():
    """tod_multiplier is stamped on each signal dict regardless of lookup path."""
    sig = make_signal(confidence=0.8, regime_type="trend")
    tod_table = {("trend", "1m", 9, "ES"): 1.2}
    result = apply_tod_adjustment([sig], tod_table, "1m", 9, symbol="ES")
    assert "tod_multiplier" in result[0]
    assert result[0]["tod_multiplier"] == 1.2
