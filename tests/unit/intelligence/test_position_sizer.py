"""Tests for the risk-based position sizing calculator."""

import pytest

from src.intelligence.trading.position_sizer import calculate_position_size


@pytest.mark.unit
def test_basic_long_position():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5085,
        direction=1,
        point_value=50,
        risk_amount=1000,
    )
    assert result.contracts == 1
    assert result.risk_per_contract == 750.0
    assert result.total_risk == 750.0
    assert result.capped is False


@pytest.mark.unit
def test_basic_short_position():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5115,
        direction=-1,
        point_value=50,
        risk_amount=1000,
    )
    assert result.contracts == 1
    assert result.risk_per_contract == 750.0
    assert result.total_risk == 750.0
    assert result.capped is False


@pytest.mark.unit
def test_max_contracts_cap():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5099,
        direction=1,
        point_value=50,
        risk_amount=10000,
        max_contracts=10,
    )
    assert result.contracts == 10
    assert result.capped is True


@pytest.mark.unit
def test_zero_risk_returns_zero():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5100,
        direction=1,
        point_value=50,
        risk_amount=1000,
    )
    assert result.contracts == 0


@pytest.mark.unit
def test_minimum_one_contract_when_affordable():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5085,
        direction=1,
        point_value=50,
        risk_amount=800,
    )
    assert result.contracts == 1
    assert result.risk_per_contract == 750.0


@pytest.mark.unit
def test_insufficient_risk_returns_zero():
    result = calculate_position_size(
        entry_price=5100,
        stop_loss=5085,
        direction=1,
        point_value=50,
        risk_amount=100,
    )
    assert result.contracts == 0


@pytest.mark.unit
def test_gold_futures_sizing():
    result = calculate_position_size(
        entry_price=2050,
        stop_loss=2040,
        direction=1,
        point_value=100,
        risk_amount=2000,
    )
    assert result.contracts == 2
    assert result.risk_per_contract == 1000.0
    assert result.total_risk == 2000.0
    assert result.capped is False
