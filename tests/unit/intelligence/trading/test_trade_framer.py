"""Tests for trade_framer zone bound computation."""

import pytest

from src.intelligence.trading.trade_framer import frame_trade


def _features_with_demand_zone():
    return {
        "atr_14": 5.0,
        "nearest_demand_high": 450.0,  # proximal edge (zone top)
        "nearest_demand_low": 445.0,  # distal edge (zone bottom)
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
        features = {
            "atr_14": 3.0,
            "nearest_supply_high": 460.0,
            "nearest_supply_low": 455.0,
            "in_supply_zone": 1.0,
            "swing_high": 462.0,
        }
        frame = frame_trade("supply_demand_short", -1, 457.0, features, atr=3.0)
        assert frame.zone_low < frame.zone_high


@pytest.mark.unit
class TestPullbackStalenessGate:
    """at_pullback entries where close has already passed T1 must be rejected."""

    def _short_pullback_features(self, close_price: float) -> dict:
        # nearest_resistance=120 > plugin entry=100 → at_pullback resolves to 120
        # ATR=5, stop=120+2×5=130, risk=10, T1=120-2×10=100 (ATR fallback 2.0×risk)
        return {
            "nearest_resistance": 120.0,
            "close_price": close_price,
        }

    def _long_pullback_features(self, close_price: float) -> dict:
        # nearest_support=80 < plugin entry=100 → at_pullback resolves to 80
        # ATR=5, stop=80-2×5=70, risk=10, T1=80+2×10=100 (ATR fallback 2.0×risk)
        return {
            "nearest_support": 80.0,
            "close_price": close_price,
        }

    def test_short_pullback_rejected_when_close_below_t1(self):
        """SHORT at_pullback: close already below T1 → not viable."""
        features = self._short_pullback_features(close_price=90.0)  # below T1≈100
        frame = frame_trade("trend_short", -1, 100.0, features, atr=5.0)
        assert not frame.viable
        assert frame.rejection_reason == "pullback_entry_price_past_t1"

    def test_short_pullback_viable_when_close_above_t1(self):
        """SHORT at_pullback: close between T1 and entry → viable (normal pending)."""
        features = self._short_pullback_features(close_price=110.0)  # between T1≈100 and entry=120
        frame = frame_trade("trend_short", -1, 100.0, features, atr=5.0)
        assert frame.viable

    def test_long_pullback_rejected_when_close_above_t1(self):
        """LONG at_pullback: close already above T1 → not viable."""
        features = self._long_pullback_features(close_price=110.0)  # above T1≈100
        frame = frame_trade("trend_long", 1, 100.0, features, atr=5.0)
        assert not frame.viable
        assert frame.rejection_reason == "pullback_entry_price_past_t1"

    def test_long_pullback_viable_when_close_below_t1(self):
        """LONG at_pullback: close between entry and T1 → viable."""
        features = self._long_pullback_features(close_price=90.0)  # between entry=80 and T1≈100
        frame = frame_trade("trend_long", 1, 100.0, features, atr=5.0)
        assert frame.viable

    def test_at_close_entry_not_affected_by_gate(self):
        """Non-pullback (at_close) entries are never filtered by the pullback gate."""
        # mean_reversion uses at_close; close=entry so close can never be past T1 on same bar
        features = {"close_price": 450.0, "atr_14": 5.0}
        frame = frame_trade("mean_reversion_long", 1, 450.0, features, atr=5.0)
        # Gate should not fire — viable determined only by RR
        assert frame.rejection_reason != "pullback_entry_price_past_t1"
