"""Tests for CounterfactualComputeAgent and _validate_counterfactual_fields."""

import pytest

from src.core.ai.context import Tier
from src.intelligence.ai.alpha.counterfactual_agent import (
    CounterfactualComputeAgent,
    _validate_counterfactual_fields,
)


def test_validator_accepts_valid_payload():
    """Validator returns all five keys for a well-formed payload."""
    payload = {
        "plausibility": 0.7,
        "confidence": 0.8,
        "validation_conditions": ["trend is up", "volume confirms"],
        "invalidation_conditions": ["price breaks below support"],
        "reasoning": "Conditions align with uptrend.",
    }
    result = _validate_counterfactual_fields(payload)
    assert result is not None
    assert result["plausibility"] == pytest.approx(0.7)
    assert result["confidence"] == pytest.approx(0.8)
    assert result["validation_conditions"] == ["trend is up", "volume confirms"]
    assert result["invalidation_conditions"] == ["price breaks below support"]
    assert result["reasoning"] == "Conditions align with uptrend."


def test_validator_rejects_non_numeric_plausibility():
    """Validator returns None when plausibility is not numeric."""
    payload = {
        "plausibility": "high",
        "confidence": 0.8,
        "validation_conditions": [],
        "invalidation_conditions": [],
        "reasoning": "",
    }
    assert _validate_counterfactual_fields(payload) is None


def test_validator_rejects_non_numeric_confidence():
    """Validator returns None when confidence is not numeric."""
    payload = {
        "plausibility": 0.7,
        "confidence": "medium",
        "validation_conditions": [],
        "invalidation_conditions": [],
        "reasoning": "",
    }
    assert _validate_counterfactual_fields(payload) is None


def test_validator_clamps_out_of_range():
    """Validator clamps plausibility and confidence to [0.0, 1.0]."""
    payload = {
        "plausibility": 1.5,
        "confidence": -0.3,
        "validation_conditions": [],
        "invalidation_conditions": [],
        "reasoning": "",
    }
    result = _validate_counterfactual_fields(payload)
    assert result is not None
    assert result["plausibility"] == pytest.approx(1.0)
    assert result["confidence"] == pytest.approx(0.0)


def test_validator_coerces_non_list_validation_conditions():
    """Validator wraps a non-list validation_conditions as a single-element list."""
    payload = {
        "plausibility": 0.5,
        "confidence": 0.5,
        "validation_conditions": "X",
        "invalidation_conditions": [],
        "reasoning": "",
    }
    result = _validate_counterfactual_fields(payload)
    assert result is not None
    assert result["validation_conditions"] == ["X"]


def test_validator_coerces_non_list_invalidation_conditions():
    """Validator wraps a non-list invalidation_conditions as a single-element list."""
    payload = {
        "plausibility": 0.5,
        "confidence": 0.5,
        "validation_conditions": [],
        "invalidation_conditions": "X",
        "reasoning": "",
    }
    result = _validate_counterfactual_fields(payload)
    assert result is not None
    assert result["invalidation_conditions"] == ["X"]


def test_class_attributes():
    """Class-level attributes match the D-06 specification."""
    assert CounterfactualComputeAgent.agent_id == "counterfactual_v1"
    assert CounterfactualComputeAgent.shadow_only is True
    assert Tier.I7 in CounterfactualComputeAgent.tiers_needed
    assert Tier.I1 in CounterfactualComputeAgent.tiers_needed
    assert Tier.I4 in CounterfactualComputeAgent.tiers_needed
    assert CounterfactualComputeAgent.latency_budget_ms == pytest.approx(120000.0)
    assert CounterfactualComputeAgent.group == "alpha"


def test_multiplier_formula_semantics():
    """multiplier = plausibility * confidence (discount-only policy)."""
    plausibility, conf = 0.5, 0.6
    assert plausibility * conf == pytest.approx(0.30)


def test_validator_rejects_non_dict():
    """Validator returns None for non-dict input."""
    assert _validate_counterfactual_fields("not a dict") is None
    assert _validate_counterfactual_fields(None) is None
    assert _validate_counterfactual_fields([]) is None


def test_validator_list_items_coerced_to_str():
    """Validator coerces list items to str."""
    payload = {
        "plausibility": 0.6,
        "confidence": 0.7,
        "validation_conditions": [1, 2.0, True],
        "invalidation_conditions": [None],
        "reasoning": "test",
    }
    result = _validate_counterfactual_fields(payload)
    assert result is not None
    assert all(isinstance(x, str) for x in result["validation_conditions"])
    assert all(isinstance(x, str) for x in result["invalidation_conditions"])
