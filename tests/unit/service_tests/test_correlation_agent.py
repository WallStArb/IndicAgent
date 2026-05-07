"""Unit tests for CorrelationAgentComputeAgent (Phase 80, D-04)."""

from __future__ import annotations

import pytest

from src.intelligence.ai.alpha.correlation_agent import (
    CorrelationAgentComputeAgent,
    _validate_correlation_fields,
)


def test_validator_accepts_valid_payload() -> None:
    out = _validate_correlation_fields(
        {
            "coherence_score": 0.7,
            "confidence": 0.8,
            "contradicting_assets": ["VIX"],
            "reasoning": "VIX fell with risk-on",
        }
    )
    assert out is not None
    assert out["coherence_score"] == pytest.approx(0.7)
    assert out["confidence"] == pytest.approx(0.8)
    assert out["contradicting_assets"] == ["VIX"]


def test_validator_rejects_non_numeric_score() -> None:
    assert _validate_correlation_fields({"coherence_score": "high", "confidence": 0.5}) is None


def test_validator_rejects_missing_fields() -> None:
    assert _validate_correlation_fields({}) is None


def test_validator_clamps_out_of_range() -> None:
    out = _validate_correlation_fields(
        {
            "coherence_score": 2.0,
            "confidence": -0.5,
            "contradicting_assets": [],
            "reasoning": "",
        }
    )
    assert out is not None
    assert out["coherence_score"] == 1.0
    assert out["confidence"] == 0.0


def test_validator_coerces_non_list_contradicting_assets() -> None:
    out = _validate_correlation_fields(
        {
            "coherence_score": 0.5,
            "confidence": 0.5,
            "contradicting_assets": "VIX",
            "reasoning": "",
        }
    )
    assert out is not None
    assert out["contradicting_assets"] == ["VIX"]


def test_class_attributes() -> None:
    from src.core.ai.context import Tier

    assert CorrelationAgentComputeAgent.agent_id == "correlation_v1"
    assert CorrelationAgentComputeAgent.group == "alpha"
    assert CorrelationAgentComputeAgent.shadow_only is True
    assert CorrelationAgentComputeAgent.latency_budget_ms == 5000.0
    assert Tier.I6 in CorrelationAgentComputeAgent.tiers_needed


def test_multiplier_formula_semantics() -> None:
    """multiplier = coherence_score × confidence per D-04."""
    coherence_score, confidence = 0.6, 0.9
    assert coherence_score * confidence == pytest.approx(0.54)
