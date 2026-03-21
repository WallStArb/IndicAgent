"""Tests for src/intelligence/trading/confidence_utils.py."""

from __future__ import annotations

from src.intelligence.trading.confidence_utils import (
    CONF_CEIL,
    CONF_FLOOR,
    compose_confidence,
)


def test_conf_floor_value():
    assert CONF_FLOOR == 0.10


def test_conf_ceil_value():
    assert CONF_CEIL == 0.95


def test_compose_confidence_midpoint():
    assert compose_confidence(0.5) == 0.5


def test_compose_confidence_zero_clamps_to_floor():
    assert compose_confidence(0.0) == CONF_FLOOR


def test_compose_confidence_negative_clamps_to_floor():
    assert compose_confidence(-0.5) == CONF_FLOOR


def test_compose_confidence_one_clamps_to_ceil():
    assert compose_confidence(1.0) == CONF_CEIL


def test_compose_confidence_above_one_clamps_to_ceil():
    assert compose_confidence(1.5) == CONF_CEIL


def test_compose_confidence_four_decimal_rounding():
    result = compose_confidence(0.12345)
    assert result == 0.1235


def test_compose_confidence_at_floor_boundary():
    assert compose_confidence(0.10) == 0.10


def test_compose_confidence_at_ceil_boundary():
    assert compose_confidence(0.95) == 0.95


def test_compose_confidence_just_inside_bounds():
    assert compose_confidence(0.50) == 0.5000
