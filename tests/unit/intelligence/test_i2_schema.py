"""Tests for I2Events schema model and IntelligenceEvent.i2 field."""

import pytest
from pydantic import ValidationError

from src.intelligence.schemas import I2Events


def test_i2events_fields_present():
    e = I2Events()
    assert hasattr(e, "rsi_crossed_30_up")
    assert hasattr(e, "adx_trend_confirmed")


def test_intelligence_event_has_i2_field():
    from src.intelligence.schemas import IntelligenceEvent

    assert "i2" in IntelligenceEvent.model_fields


def test_macd_events_outputs_has_new_accel_fields():
    from src.intelligence.features.i3_structure.macd_events import plugin as macd_events_plugin

    assert "macd_hist_accel" in macd_events_plugin.outputs
    assert "macd_hist_contracting" in macd_events_plugin.outputs
    assert len(macd_events_plugin.outputs) == 8  # 6 original + 2 new


# --- MACD fields removed from I2Events (migrated to I3Structure) ---

_MACD_REMOVED_FIELDS = [
    "macd_cross_bullish",
    "macd_cross_bearish",
    "macd_cross_bars_ago",
    "macd_hist_positive",
    "macd_hist_turning_up",
    "macd_negative_support_test",
    "macd_price_divergence_bullish",
    "macd_price_divergence_bearish",
]


@pytest.mark.parametrize("field", _MACD_REMOVED_FIELDS)
def test_macd_field_absent_from_i2events(field: str) -> None:
    assert field not in I2Events.model_fields


def test_extra_field_raises_validation_error():
    """I2Events extra='forbid' must reject undeclared fields."""
    with pytest.raises(ValidationError):
        I2Events(**{"undeclared_field": 1})


def test_macd_cross_bullish_raises_validation_error():
    """Attempting to set former MACD field must raise ValidationError."""
    with pytest.raises(ValidationError):
        I2Events(**{"macd_cross_bullish": 1.0})


# --- Composite plugin fields present ---


@pytest.mark.parametrize("field", ["rsi_accel", "deriv_osc", "exhaustion_score", "accel_regime"])
def test_composite_field_present(field: str) -> None:
    assert hasattr(I2Events(), field)
