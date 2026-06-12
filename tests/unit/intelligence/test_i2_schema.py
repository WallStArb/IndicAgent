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


def test_macd_cross_bullish_absent_from_i2events():
    """macd_cross_bullish was removed from I2Events — belongs to I3Structure."""
    assert "macd_cross_bullish" not in I2Events.model_fields


def test_macd_cross_bearish_absent_from_i2events():
    assert "macd_cross_bearish" not in I2Events.model_fields


def test_macd_cross_bars_ago_absent_from_i2events():
    assert "macd_cross_bars_ago" not in I2Events.model_fields


def test_macd_hist_positive_absent_from_i2events():
    assert "macd_hist_positive" not in I2Events.model_fields


def test_macd_hist_turning_up_absent_from_i2events():
    assert "macd_hist_turning_up" not in I2Events.model_fields


def test_macd_negative_support_test_absent_from_i2events():
    assert "macd_negative_support_test" not in I2Events.model_fields


def test_macd_price_divergence_bullish_absent_from_i2events():
    assert "macd_price_divergence_bullish" not in I2Events.model_fields


def test_macd_price_divergence_bearish_absent_from_i2events():
    assert "macd_price_divergence_bearish" not in I2Events.model_fields


def test_extra_field_raises_validation_error():
    """I2Events extra='forbid' must reject undeclared fields."""
    with pytest.raises(ValidationError):
        I2Events(**{"undeclared_field": 1})


def test_macd_cross_bullish_raises_validation_error():
    """Attempting to set former MACD field must raise ValidationError."""
    with pytest.raises(ValidationError):
        I2Events(**{"macd_cross_bullish": 1.0})


# --- Composite plugin fields present ---


def test_rsi_accel_present():
    assert hasattr(I2Events(), "rsi_accel")


def test_deriv_osc_present():
    assert hasattr(I2Events(), "deriv_osc")


def test_exhaustion_score_present():
    assert hasattr(I2Events(), "exhaustion_score")


def test_accel_regime_present():
    assert hasattr(I2Events(), "accel_regime")
