"""Tests for computational correctness validation engine."""

import pytest
import numpy as np
from src.validation.validation_engine import ComputationalCorrectnessValidator


@pytest.mark.asyncio
async def test_validate_field_within_tolerance():
    """Test field validation with values within tolerance."""
    validator = ComputationalCorrectnessValidator(None)

    ref_values = np.array([50.0, 51.0, 52.0, 53.0, 54.0])
    prod_values = np.array([50.01, 51.01, 52.01, 53.01, 54.01])

    result = validator.validate_field("test_field", ref_values, prod_values)

    assert result["field"] == "test_field"
    assert result["passed"] is True
    assert result["max_diff"] < 0.02
    assert result["samples"] == 5
