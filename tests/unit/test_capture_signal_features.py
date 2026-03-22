"""Tests for capture_signal_features() and ConfluenceWeightProfile in confidence_utils.py."""

from __future__ import annotations

import pytest

from src.intelligence.trading.confidence_utils import (
    FAMILY_PROFILES,
    ConfluenceWeightProfile,
    capture_signal_features,
)

# ---------------------------------------------------------------------------
# Test 1: complete features dict returns full shadow dict
# ---------------------------------------------------------------------------


def test_capture_signal_features_all_fields_present() -> None:
    features = {
        "ctf_score": 0.81,
        "ctf_trend_alignment": 0.74,
        "ctf_structure_alignment": 0.60,
        "ctf_regime_agreement": 0.55,
        "ctf_fvg_alignment": 0.40,
        "ctf_ob_alignment": 0.35,
        "exhaustion_score": 0.45,
        "exhaustion_side": "bull",
        "exhaustion_bars": 2.0,
    }
    shadow = capture_signal_features(
        features=features,
        direction=1,
        profile_name="trend",
        existing_confidence=0.72,
    )

    assert shadow["profile"] == "trend"
    assert shadow["existing_confidence"] == round(0.72, 4)
    assert shadow["ctf_score"] == 0.81
    assert shadow["ctf_trend_alignment"] == 0.74
    assert shadow["ctf_structure_alignment"] == 0.60
    assert shadow["ctf_regime_agreement"] == 0.55
    assert shadow["ctf_fvg_alignment"] == 0.40
    assert shadow["ctf_ob_alignment"] == 0.35
    assert shadow["exhaustion_score"] == 0.45
    assert shadow["exhaustion_side"] == "bull"
    assert shadow["exhaustion_bars"] == 2.0

    # Full key set (8 confluence/meta + 4 I4 macro context + 3 exhaustion = 15 keys)
    expected_keys = {
        "profile",
        "existing_confidence",
        "ctf_score",
        "ctf_trend_alignment",
        "ctf_structure_alignment",
        "ctf_regime_agreement",
        "ctf_fvg_alignment",
        "ctf_ob_alignment",
        "exhaustion_score",
        "exhaustion_side",
        "exhaustion_bars",
        "vix_level",
        "vix_z",
        "eq_spread_z",
        "eq_pairs_confirming",
    }
    assert set(shadow.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test 2: missing fields default to 0.0
# ---------------------------------------------------------------------------


def test_capture_signal_features_missing_fields_default_to_zero() -> None:
    shadow = capture_signal_features(
        features={},
        direction=1,
        profile_name="smc",
        existing_confidence=0.55,
    )

    assert shadow["ctf_score"] == 0.0
    assert shadow["ctf_trend_alignment"] == 0.0
    assert shadow["ctf_structure_alignment"] == 0.0
    assert shadow["ctf_regime_agreement"] == 0.0
    assert shadow["ctf_fvg_alignment"] == 0.0
    assert shadow["ctf_ob_alignment"] == 0.0
    assert shadow["exhaustion_score"] == 0.0
    assert shadow["exhaustion_side"] == "none"
    assert shadow["exhaustion_bars"] == 0.0


# ---------------------------------------------------------------------------
# Test 3: exempt_exhaustion profile sets exhaustion fields to None
# ---------------------------------------------------------------------------


def test_capture_signal_features_exempt_exhaustion_omits_exhaustion() -> None:
    features = {
        "ctf_score": 0.70,
        "exhaustion_score": 0.90,
        "exhaustion_side": "bear",
        "exhaustion_bars": 4.0,
    }
    shadow = capture_signal_features(
        features=features,
        direction=-1,
        profile_name="exempt_exhaustion",
        existing_confidence=0.65,
    )

    assert shadow["profile"] == "exempt_exhaustion"
    assert shadow["ctf_score"] == 0.70
    # Exhaustion fields must be None for exempt profile
    assert shadow["exhaustion_score"] is None
    assert shadow["exhaustion_side"] is None
    assert shadow["exhaustion_bars"] is None


# ---------------------------------------------------------------------------
# Test 4: ConfluenceWeightProfile has all weight fields = 0.0
# ---------------------------------------------------------------------------


def test_confluence_weight_profile_all_weights_are_zero() -> None:
    profile = ConfluenceWeightProfile(name="trend")

    assert profile.w_ctf_score == 0.0
    assert profile.w_ctf_trend_alignment == 0.0
    assert profile.w_ctf_structure_alignment == 0.0
    assert profile.w_ctf_regime_agreement == 0.0
    assert profile.w_ctf_fvg_alignment == 0.0
    assert profile.w_ctf_ob_alignment == 0.0
    assert profile.w_exhaustion == 0.0


def test_confluence_weight_profile_is_frozen() -> None:
    profile = ConfluenceWeightProfile(name="smc")
    with pytest.raises((AttributeError, TypeError)):
        profile.w_ctf_score = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 5: FAMILY_PROFILES has exactly 6 keys
# ---------------------------------------------------------------------------


def test_family_profiles_has_exactly_six_keys() -> None:
    expected_keys = {
        "trend",
        "mean_reversion",
        "smc",
        "microstructure",
        "session",
        "exempt_exhaustion",
    }
    assert set(FAMILY_PROFILES.keys()) == expected_keys


def test_family_profiles_all_values_are_confluence_weight_profile() -> None:
    for name, profile in FAMILY_PROFILES.items():
        assert isinstance(profile, ConfluenceWeightProfile), (
            f"FAMILY_PROFILES['{name}'] is {type(profile)}, expected ConfluenceWeightProfile"
        )
        assert profile.name == name


# ---------------------------------------------------------------------------
# I4 macro context shadow fields (Phase 46.1) — Tests 6–9
# ---------------------------------------------------------------------------


def test_new_fields_present_when_provided() -> None:
    """All 4 I4 macro context fields are captured when present in features."""
    features = {
        "ctf_score": 0.6,
        "vix_level": 18.5,
        "vix_z": -0.32,
        "eq_spread_z": 2.1,
        "eq_pairs_confirming": 1.0,
    }
    shadow = capture_signal_features(features, 1, "trend", 0.7)

    assert shadow["vix_level"] == 18.5
    assert shadow["vix_z"] == -0.32
    assert shadow["eq_spread_z"] == 2.1
    assert shadow["eq_pairs_confirming"] == 1.0


def test_new_fields_none_when_missing() -> None:
    """Per D-06: absent I4 macro fields default to None, never 0.0."""
    features = {"ctf_score": 0.5}  # minimal — no I4 macro fields
    shadow = capture_signal_features(features, 1, "trend", 0.7)

    assert shadow["vix_level"] is None
    assert shadow["vix_z"] is None
    assert shadow["eq_spread_z"] is None
    assert shadow["eq_pairs_confirming"] is None


def test_new_fields_preserve_none_not_zero() -> None:
    """Per D-06: None != 0.0. 0.0 is a valid z-score value."""
    features = {"vix_level": 0.0, "vix_z": 0.0}
    shadow = capture_signal_features(features, 1, "trend", 0.7)

    assert shadow["vix_level"] == 0.0  # preserved, not None
    assert shadow["vix_z"] == 0.0  # preserved, not None
    assert shadow["eq_spread_z"] is None  # absent -> None


def test_shadow_key_count_non_exempt_is_15() -> None:
    """Non-exempt profile: 8 confluence/meta + 4 I4 macro context + 3 exhaustion = 15 keys."""
    shadow = capture_signal_features({}, 1, "trend", 0.7)
    assert len(shadow) == 15


def test_shadow_key_count_exempt_is_15() -> None:
    """exempt_exhaustion profile also has 15 keys (exhaustion fields are None, not absent)."""
    shadow = capture_signal_features({}, 1, "exempt_exhaustion", 0.7)
    assert len(shadow) == 15
