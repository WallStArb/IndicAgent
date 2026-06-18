"""Tests for src/intelligence/trading/confidence.py."""

from __future__ import annotations

from src.intelligence.trading.confidence import (
    CONF_CEIL,
    compose_confidence,
)


def test_conf_ceil_value():
    assert CONF_CEIL == 0.95


def test_compose_confidence_midpoint():
    assert compose_confidence(0.5) == 0.5


def test_compose_confidence_zero_passes_through():
    """Zero is a valid raw signal confidence — no longer boosted to a floor."""
    assert compose_confidence(0.0) == 0.0


def test_compose_confidence_negative_clamps_to_zero():
    """Negative is invalid; clamp to 0.0, not to the old floor."""
    assert compose_confidence(-0.5) == 0.0


def test_compose_confidence_sub_floor_passes_through():
    """0.03 is below the old CONF_FLOOR=0.10 — must now pass through unchanged."""
    assert compose_confidence(0.03) == 0.03


def test_compose_confidence_one_clamps_to_ceil():
    assert compose_confidence(1.0) == CONF_CEIL


def test_compose_confidence_above_one_clamps_to_ceil():
    assert compose_confidence(1.5) == CONF_CEIL


def test_compose_confidence_four_decimal_rounding():
    result = compose_confidence(0.12345)
    assert result == 0.1235


def test_compose_confidence_at_ceil_boundary():
    assert compose_confidence(0.95) == 0.95


def test_compose_confidence_just_inside_ceil():
    assert compose_confidence(0.50) == 0.5000
