"""Tests for I2Events schema model and IntelligenceEvent.i2 field."""


def test_i2events_fields_present():
    from src.intelligence.schemas import I2Events

    e = I2Events()
    assert hasattr(e, "macd_cross_bullish")
    assert hasattr(e, "rsi_crossed_30_up")
    assert hasattr(e, "adx_trend_confirmed")


def test_intelligence_event_has_i2_field():
    from src.intelligence.schemas import IntelligenceEvent

    assert "i2" in IntelligenceEvent.model_fields
