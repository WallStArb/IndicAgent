"""Schema contract tests for I2Events and related tier models."""

import pytest
from pydantic import ValidationError

from src.intelligence.schemas import I2Events


class TestI2EventsSchema:
    def test_rejects_undeclared_extra_field(self):
        """I2Events must raise ValidationError on any undeclared field."""
        with pytest.raises(ValidationError):
            I2Events(**{"undeclared_xyz": 1.0})

    def test_rejects_former_macd_cross_bullish(self):
        """macd_cross_bullish was removed from I2Events (belongs to I3Structure)."""
        with pytest.raises(ValidationError):
            I2Events(**{"macd_cross_bullish": 1.0})

    def test_accepts_all_19_composite_fields(self):
        """All 19 composite plugin fields must be accepted without error."""
        composite_fields = {
            "rsi_accel": 0.1,
            "macd_accel": 0.2,
            "roc_accel": 0.3,
            "inflection_flag": 1.0,
            "rsi_curvature": 0.05,
            "macd_hist_slope": 0.01,
            "price_accel": 0.002,
            "hma_slope": 0.5,
            "hma_accel": 0.1,
            "deriv_osc": 0.3,
            "deriv_osc_signal": 0.2,
            "deriv_osc_cross_bullish": 1.0,
            "deriv_osc_cross_bearish": 0.0,
            "exhaustion_score": 0.7,
            "exhaustion_side": "long",
            "exhaustion_bars": 3.0,
            "accel_regime": "trending",
            "accel_score": 0.6,
            "accel_agreement": 0.8,
        }
        event = I2Events(**composite_fields)
        assert event.rsi_accel == 0.1
        assert event.exhaustion_side == "long"
        assert event.accel_regime == "trending"

    def test_field_count_is_45(self):
        """I2Events must declare exactly 45 fields."""
        assert len(I2Events.model_fields) == 45

    def test_none_defaults_on_empty_construction(self):
        """I2Events() with no args must not raise."""
        event = I2Events()
        assert event.rsi_accel is None
        assert event.exhaustion_side is None
