"""Characterization tests for trade_framer emergency ATR fallback.

These tests document and pin existing behavior — do not modify without
understanding the zero-ATR guard math.
"""

import pytest

from src.intelligence.trading.trade_framer import (
    ATR_EMERGENCY_FALLBACK_PCT,
    EPSILON_TOLERANCE,
    frame_trade,
)


@pytest.mark.unit
class TestTradeFramerZeroATRCharacterization:
    """Characterization tests pinning zero-ATR emergency fallback in frame_trade()."""

    def test_zero_atr_does_not_crash(self):
        """Characterization: zero ATR must not raise — emergency fallback activates."""
        features = {"swing_low": 4985.0, "sr_nearest_resistance": 5025.0}
        result = frame_trade("trend_long", 1, 5000.0, features, atr=0.0)
        assert result is not None
        assert result.entry == pytest.approx(5000.0)

    def test_zero_atr_emergency_is_point_one_percent_of_price(self):
        """Characterization: emergency ATR = abs(entry) * 0.001 = 0.1% of price."""
        assert ATR_EMERGENCY_FALLBACK_PCT == 0.001
        # entry=5000 → emergency_atr=5.0 → fallback stop = 5000 - 5.0*2.0 = 4990.0
        result = frame_trade("trend_long", 1, 5000.0, {}, atr=0.0)
        assert result.stop == pytest.approx(4990.0, abs=0.1)

    def test_negative_atr_also_triggers_emergency(self):
        """Characterization: negative ATR satisfies atr <= EPSILON_TOLERANCE — same guard fires."""
        # entry=4000 → emergency_atr=4.0 → fallback stop = 4000 - 4.0*2.0 = 3992.0
        result = frame_trade("trend_long", 1, 4000.0, {}, atr=-1.0)
        assert result.stop == pytest.approx(3992.0, abs=0.1)
