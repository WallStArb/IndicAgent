"""Tests for CounterfactualComputeAgent and CounterfactualResult."""

import pytest

from src.core.ai.context import Tier
from src.intelligence.ai.alpha.counterfactual_agent import (
    CounterfactualComputeAgent,
    CounterfactualResult,
)


def test_result_accepts_valid_payload():
    """CounterfactualResult parses a well-formed payload."""
    result = CounterfactualResult(
        plausibility=0.7,
        confidence=0.8,
        validation_conditions=["trend is up", "volume confirms"],
        invalidation_conditions=["price breaks below support"],
        reasoning="Conditions align with uptrend.",
    )
    assert result.plausibility == pytest.approx(0.7)
    assert result.confidence == pytest.approx(0.8)
    assert result.validation_conditions == ["trend is up", "volume confirms"]
    assert result.invalidation_conditions == ["price breaks below support"]
    assert result.reasoning == "Conditions align with uptrend."


def test_result_rejects_non_numeric_plausibility():
    """ValidationError when plausibility is not numeric."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CounterfactualResult(
            plausibility="high",
            confidence=0.8,
            validation_conditions=[],
            invalidation_conditions=[],
            reasoning="",
        )


def test_result_rejects_non_numeric_confidence():
    """ValidationError when confidence is not numeric."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CounterfactualResult(
            plausibility=0.7,
            confidence="medium",
            validation_conditions=[],
            invalidation_conditions=[],
            reasoning="",
        )


def test_result_clamps_out_of_range():
    """CounterfactualResult clamps plausibility and confidence to [0.0, 1.0]."""
    result = CounterfactualResult(
        plausibility=1.5,
        confidence=-0.3,
        validation_conditions=[],
        invalidation_conditions=[],
        reasoning="",
    )
    assert result.plausibility == pytest.approx(1.0)
    assert result.confidence == pytest.approx(0.0)


def test_result_coerces_non_list_validation_conditions():
    """Wraps non-list validation_conditions as a single-element list."""
    result = CounterfactualResult(
        plausibility=0.5,
        confidence=0.5,
        validation_conditions="X",
        invalidation_conditions=[],
        reasoning="",
    )
    assert result.validation_conditions == ["X"]


def test_result_coerces_non_list_invalidation_conditions():
    """Wraps non-list invalidation_conditions as a single-element list."""
    result = CounterfactualResult(
        plausibility=0.5,
        confidence=0.5,
        validation_conditions=[],
        invalidation_conditions="X",
        reasoning="",
    )
    assert result.invalidation_conditions == ["X"]


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


def test_result_rejects_non_dict():
    """ValidationError for invalid input types."""
    from pydantic import ValidationError

    with pytest.raises((ValidationError, TypeError)):
        CounterfactualResult.model_validate("not a dict")


def test_result_list_items_coerced_to_str():
    """List items are coerced to str."""
    result = CounterfactualResult(
        plausibility=0.6,
        confidence=0.7,
        validation_conditions=[1, 2.0, True],
        invalidation_conditions=[None],
        reasoning="test",
    )
    assert all(isinstance(x, str) for x in result.validation_conditions)
    assert all(isinstance(x, str) for x in result.invalidation_conditions)
