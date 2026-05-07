"""Unit tests for RegimeCoherenceAgentComputeAgent and _validate_regime_coherence_fields."""

from __future__ import annotations

import pytest

from src.core.ai.context import Tier
from src.intelligence.ai.alpha.regime_coherence_agent import (
    RegimeCoherenceAgentComputeAgent,
    _validate_regime_coherence_fields,
)

# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


def test_validator_accepts_valid_payload() -> None:
    """Valid payload with both numerics, list mismatches, and string reasoning."""
    data = {
        "regime_fit": 0.8,
        "confidence": 0.7,
        "mismatches": ["mean_reversion_in_trend"],
        "reasoning": "Setup type contradicts trending regime.",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is not None
    assert result["regime_fit"] == pytest.approx(0.8)
    assert result["confidence"] == pytest.approx(0.7)
    assert result["mismatches"] == ["mean_reversion_in_trend"]
    assert result["reasoning"] == "Setup type contradicts trending regime."


def test_validator_rejects_non_numeric_regime_fit() -> None:
    """Non-numeric regime_fit should return None."""
    data = {
        "regime_fit": "high",
        "confidence": 0.5,
        "mismatches": [],
        "reasoning": "some reasoning",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is None


def test_validator_rejects_non_numeric_confidence() -> None:
    """Non-numeric confidence should return None."""
    data = {
        "regime_fit": 0.6,
        "confidence": None,
        "mismatches": [],
        "reasoning": "some reasoning",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is None


def test_validator_clamps_out_of_range() -> None:
    """Values outside [0,1] should be clamped."""
    data = {
        "regime_fit": 1.5,
        "confidence": -0.2,
        "mismatches": [],
        "reasoning": "out of range values",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is not None
    assert result["regime_fit"] == pytest.approx(1.0)
    assert result["confidence"] == pytest.approx(0.0)


def test_validator_coerces_non_list_mismatches() -> None:
    """Non-list mismatches should be coerced to [str(value)]."""
    data = {
        "regime_fit": 0.5,
        "confidence": 0.5,
        "mismatches": "single_mismatch_string",
        "reasoning": "coerce test",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is not None
    assert result["mismatches"] == ["single_mismatch_string"]


def test_validator_coerces_list_elements_to_str() -> None:
    """List elements should be coerced to str."""
    data = {
        "regime_fit": 0.5,
        "confidence": 0.5,
        "mismatches": [1, 2.0, "three"],
        "reasoning": "coerce list elements",
    }
    result = _validate_regime_coherence_fields(data)
    assert result is not None
    assert result["mismatches"] == ["1", "2.0", "three"]


# ---------------------------------------------------------------------------
# Class attribute tests
# ---------------------------------------------------------------------------


def test_class_attributes() -> None:
    """Verify mandatory class attributes."""
    assert RegimeCoherenceAgentComputeAgent.agent_id == "regime_coherence_v1"
    assert RegimeCoherenceAgentComputeAgent.shadow_only is True
    assert Tier.I4 in RegimeCoherenceAgentComputeAgent.tiers_needed
    assert Tier.I7 in RegimeCoherenceAgentComputeAgent.tiers_needed
    assert Tier.SMC in RegimeCoherenceAgentComputeAgent.tiers_needed
    assert RegimeCoherenceAgentComputeAgent.latency_budget_ms == 5000.0
    assert RegimeCoherenceAgentComputeAgent.group == "alpha"


# ---------------------------------------------------------------------------
# Multiplier formula test
# ---------------------------------------------------------------------------


def test_multiplier_formula_semantics() -> None:
    """regime_fit × confidence equals the expected product."""
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
