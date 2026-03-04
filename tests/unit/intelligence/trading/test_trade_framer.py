"""Tests for trade_framer zone bound computation."""
import pytest
from src.intelligence.trading.trade_framer import TradeFrame, frame_trade


def _features_with_demand_zone():
    return {
        "atr_14": 5.0,
        "nearest_demand_high": 450.0,   # proximal edge (zone top)
        "nearest_demand_low": 445.0,    # distal edge (zone bottom)
        "nearest_supply_high": 460.0,
        "nearest_supply_low": 455.0,
        "in_demand_zone": 1.0,
        "swing_low": 444.0,
    }


def _features_with_fvg():
    return {
        "atr_14": 5.0,
        "fvg_type": 1.0,
        "fvg_top": 452.0,
        "fvg_bottom": 448.0,
        "swing_low": 446.0,
    }


@pytest.mark.unit
class TestZoneBounds:
    def test_demand_zone_entry_sets_structural_zone_long(self):
        """supply_demand long: zone_low = nearest_demand_low, zone_high = nearest_demand_high."""
        frame = frame_trade("supply_demand_long", 1, 451.0, _features_with_demand_zone(), atr=5.0)
        assert frame.zone_low == 445.0
        assert frame.zone_high == 450.0

    def test_fvg_entry_sets_fvg_zone_long(self):
        """FVG fill long: zone is FVG bottom to top."""
        frame = frame_trade("fvg_fill_long", 1, 449.0, _features_with_fvg(), atr=5.0)
        assert frame.zone_low == 448.0
        assert frame.zone_high == 452.0

    def test_atr_fallback_zone_when_no_structural(self):
        """at_close entry with no structural zone: fallback = entry ± ATR multiples."""
        features = {"atr_14": 5.0, "swing_low": 444.0}
        frame = frame_trade("trend_long", 1, 450.0, features, atr=5.0)
        # At-close entry, no demand zone → ATR fallback
        assert frame.zone_low == pytest.approx(450.0 - 5.0 * 1.0)
        assert frame.zone_high == pytest.approx(450.0 + 5.0 * 0.5)

    def test_zone_low_always_less_than_zone_high(self):
        """zone_low must always be < zone_high regardless of direction."""
        features = {"atr_14": 3.0, "nearest_supply_high": 460.0,
                    "nearest_supply_low": 455.0, "in_supply_zone": 1.0, "swing_high": 462.0}
        frame = frame_trade("supply_demand_short", -1, 457.0, features, atr=3.0)
        assert frame.zone_low < frame.zone_high
