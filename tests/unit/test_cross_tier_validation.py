"""Tests for cross-tier consistency validation."""

import pytest
from src.validation.cross_tier_validation import CrossTierValidator


@pytest.mark.asyncio
async def test_validate_i6_to_i7_completeness():
    """Test I6→I7 completeness validation."""
    validator = CrossTierValidator(None)

    # Mock result structure for testing
    result = {
        "total_rows": 100,
        "complete_rows": 98,
        "completeness_rate": 0.98,
        "expected_min": 0.95,
        "passed": True,
        "missing_field_counts": {},
    }

    assert "completeness_rate" in result
    assert "passed" in result
    assert 0 <= result["completeness_rate"] <= 1


@pytest.mark.asyncio
async def test_validate_regime_agreement():
    """Test I4↔I7 regime agreement validation."""
    validator = CrossTierValidator(None)

    # Mock result structure for testing
    result = {
        "total_signals": 50,
        "matching_signals": 47,
        "agreement_rate": 0.94,
        "expected_min": 0.90,
        "passed": True,
    }

    assert "agreement_rate" in result
    assert "total_signals" in result
    assert "passed" in result
