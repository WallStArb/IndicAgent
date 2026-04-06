"""ARCHIVED: 2026-04-06 Phase 61 — DataQualityMonitor null-rate tests.
DataQualityMonitor (src/intelligence/monitoring/data_quality_monitor.py) still
exists but null-rate checks are now enforced by DB constraint (migration 057).
These tests validated monitoring of a broken invariant, not a feature.
"""
# --- ARCHIVED BELOW ---

"""Tests for DataQualityMonitor schema validation.

Behavior tests:
  1. validate_input() returns True for valid event data
  2. validate_input() returns False when required fields missing
  3. validate_input() returns False when confidence out of [0,1] range
  4. validate_output() returns True for valid stage output
  5. validate_output() returns False when output confidence negative
  6. Schema validation checks type, min, max for each field
"""

from __future__ import annotations

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor


@pytest.mark.asyncio
async def test_validate_input_returns_true_for_valid_data():
    """Test 1: validate_input() returns True for valid event data."""
    monitor = DataQualityMonitor("quality_gated")
    valid_data = {
        "confidence": 0.75,
        "symbol": "ES",
        "timeframe": "1m",
    }
    result = await monitor.validate_input(valid_data)
    assert result is True


@pytest.mark.asyncio
async def test_validate_input_returns_false_when_required_field_missing():
    """Test 2: validate_input() returns False when required fields missing."""
    monitor = DataQualityMonitor("quality_gated")
    # Missing required 'symbol' field
    invalid_data = {
        "confidence": 0.75,
        "timeframe": "1m",
        # symbol is missing
    }
    result = await monitor.validate_input(invalid_data)
    assert result is False


@pytest.mark.asyncio
async def test_validate_input_returns_false_when_confidence_out_of_range():
    """Test 3: validate_input() returns False when confidence out of [0,1] range."""
    monitor = DataQualityMonitor("quality_gated")
    invalid_data = {
        "confidence": 1.5,  # > 1.0, out of range
        "symbol": "ES",
        "timeframe": "1m",
    }
    result = await monitor.validate_input(invalid_data)
    assert result is False


@pytest.mark.asyncio
async def test_validate_output_returns_true_for_valid_output():
    """Test 4: validate_output() returns True for valid stage output."""
    monitor = DataQualityMonitor("ranked")
    valid_output = {
        "adjusted_rank": 5.5,
        "confidence": 0.85,
    }
    result = await monitor.validate_output(valid_output)
    assert result is True


@pytest.mark.asyncio
async def test_validate_output_returns_false_when_confidence_negative():
    """Test 5: validate_output() returns False when output confidence negative."""
    monitor = DataQualityMonitor("ranked")
    invalid_output = {
        "adjusted_rank": 5.5,
        "confidence": -0.1,  # negative, out of range
    }
    result = await monitor.validate_output(invalid_output)
    assert result is False


@pytest.mark.asyncio
async def test_schema_validation_checks_type_min_max():
    """Test 6: Schema validation checks type, min, max for each field."""
    monitor = DataQualityMonitor("tod_adjusted")

    # tod_multiplier has type=(int,float), min=0.0, max=2.0
    invalid_type = {
        "confidence": 0.7,
        "tod_multiplier": "not_a_number",  # wrong type
    }
    result = await monitor.validate_input(invalid_type)
    assert result is False

    # tod_multiplier above max
    above_max = {
        "confidence": 0.7,
        "tod_multiplier": 3.0,  # above max 2.0
    }
    result = await monitor.validate_input(above_max)
    assert result is False

    # valid tod_multiplier
    valid = {
        "confidence": 0.7,
        "tod_multiplier": 1.2,
    }
    result = await monitor.validate_input(valid)
    assert result is True
