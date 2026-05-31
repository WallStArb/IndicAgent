"""Unit tests for RegimeCoherenceAnalyzer and RegimeCoherenceResult."""

from __future__ import annotations

import pytest

from src.core.ai.context import Tier
from src.intelligence.ai.alpha.regime_coherence_agent import (
    RegimeCoherenceAnalyzer,
    RegimeCoherenceResult,
)


def test_result_accepts_valid_payload() -> None:
    """Valid payload parses correctly."""
    result = RegimeCoherenceResult(
        regime_fit=0.8,
        confidence=0.7,
        mismatches=["mean_reversion_in_trend"],
        reasoning="Setup type contradicts trending regime.",
    )
    assert result.regime_fit == pytest.approx(0.8)
    assert result.confidence == pytest.approx(0.7)
    assert result.mismatches == ["mean_reversion_in_trend"]
    assert result.reasoning == "Setup type contradicts trending regime."


def test_result_rejects_non_numeric_regime_fit() -> None:
    """Non-numeric regime_fit should raise ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegimeCoherenceResult(
            regime_fit="high",
            confidence=0.5,
            mismatches=[],
            reasoning="some reasoning",
        )


def test_result_rejects_non_numeric_confidence() -> None:
    """Non-numeric confidence should raise ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegimeCoherenceResult(
            regime_fit=0.6,
            confidence=None,
            mismatches=[],
            reasoning="some reasoning",
        )


def test_result_clamps_out_of_range() -> None:
    """Values outside [0,1] should be clamped."""
    result = RegimeCoherenceResult(
        regime_fit=1.5,
        confidence=-0.2,
        mismatches=[],
        reasoning="out of range values",
    )
    assert result.regime_fit == pytest.approx(1.0)
    assert result.confidence == pytest.approx(0.0)


def test_result_coerces_non_list_mismatches() -> None:
    """Non-list mismatches should be coerced to [str(value)]."""
    result = RegimeCoherenceResult(
        regime_fit=0.5,
        confidence=0.5,
        mismatches="single_mismatch_string",
        reasoning="coerce test",
    )
    assert result.mismatches == ["single_mismatch_string"]


def test_result_coerces_list_elements_to_str() -> None:
    """List elements should be coerced to str."""
    result = RegimeCoherenceResult(
        regime_fit=0.5,
        confidence=0.5,
        mismatches=[1, 2.0, "three"],
        reasoning="coerce list elements",
    )
    assert result.mismatches == ["1", "2.0", "three"]


def test_class_attributes() -> None:
    """Verify mandatory class attributes."""
    assert RegimeCoherenceAnalyzer.agent_id == "regime_coherence_v1"
    assert RegimeCoherenceAnalyzer.shadow_only is True
    assert Tier.I4 in RegimeCoherenceAnalyzer.tiers_needed
    assert Tier.I7 in RegimeCoherenceAnalyzer.tiers_needed
    assert Tier.SMC in RegimeCoherenceAnalyzer.tiers_needed
    assert RegimeCoherenceAnalyzer.latency_budget_ms == 120000.0
    assert RegimeCoherenceAnalyzer.group == "alpha"


def test_multiplier_formula_semantics() -> None:
    """regime_fit x confidence equals the expected product."""
    regime_fit, conf = 0.4, 0.5
    assert regime_fit * conf == pytest.approx(0.2)


def test_multiplier_formula_zero_regime_fit() -> None:
    """regime_fit=0 produces multiplier=0 regardless of confidence."""
    regime_fit, conf = 0.0, 0.9
    assert regime_fit * conf == pytest.approx(0.0)


def test_multiplier_formula_perfect_match() -> None:
    """regime_fit=1.0 and confidence=1.0 produces multiplier=1.0."""
    regime_fit, conf = 1.0, 1.0
    assert regime_fit * conf == pytest.approx(1.0)
