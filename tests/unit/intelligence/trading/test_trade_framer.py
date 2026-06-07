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
        """at_close entry with no structural levels: zone engine returns atr tier → ATR fallback."""
        features = {"atr_14": 5.0}  # no structural levels → zone engine returns atr tier
        frame = frame_trade("trend_long", 1, 450.0, features, atr=5.0)
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


@pytest.mark.unit
class TestStopDistanceCap:
    """Structural stops beyond the per-TF ATR cap must fall back to ATR×2.0."""

    def test_5m_stop_beyond_cap_falls_back_to_atr(self):
        """5m signal: nearest_support 17×ATR below entry → capped at ATR×2.0."""
        entry = 7414.75
        atr = 8.7
        # nearest_support 148pts below entry (~17×ATR) — mimics observed bad HVNRejection signal
        features = {
            "nearest_support": 7266.455,
            "atr_14": atr,
            "timeframe": "5m",
        }
        frame = frame_trade("hvn_rejection_long", 1, entry, features, atr=atr)
        expected_stop = entry - atr * 2.0  # ATR_STOP_FALLBACK_MULTIPLIER
        assert (
            abs(frame.stop - expected_stop) < 0.01
        ), f"stop {frame.stop} not capped to ATR fallback"

    def test_5m_short_stop_beyond_cap_falls_back(self):
        """5m short signal: bearish FVG top 10×ATR above at_close entry → capped at ATR×2.0."""
        entry = 7474.25
        atr = 8.2
        # bearish FVG at 7558.75 top = 84.5pts above entry = ~10.3×ATR → exceeds 4×ATR cap
        features = {
            "fvg_type": -1.0,
            "fvg_top": 7558.75,
            "fvg_bottom": 7551.75,
            "atr_14": atr,
            "timeframe": "5m",
        }
        frame = frame_trade("mean_reversion_short", -1, entry, features, atr=atr)
        expected_stop = entry + atr * 2.0
        assert (
            abs(frame.stop - expected_stop) < 0.01
        ), f"stop {frame.stop} not capped to ATR fallback"

    def test_structural_stop_within_cap_is_preserved(self):
        """A legitimate 3×ATR structural stop on 5m must not be capped (within 4×ATR limit)."""
        entry = 7414.75
        atr = 8.7
        # swing_low 26pts below entry (~3×ATR) — inside 4×ATR cap
        features = {
            "swing_low": 7388.75,
            "atr_14": atr,
            "timeframe": "5m",
        }
        frame = frame_trade("mean_reversion_long", 1, entry, features, atr=atr)
        # Stop should be near swing_low (with buffer), not ATR fallback
        assert frame.stop < entry - atr * 2.5, f"stop {frame.stop} was aggressively capped"

    def test_1h_wider_cap_allows_larger_structural_stops(self):
        """1h signal: a 5×ATR structural stop is within the 6×ATR cap and should be preserved."""
        entry = 7414.75
        atr = 25.0
        # swing_low 5×ATR below entry — inside 6×ATR 1h cap
        features = {
            "swing_low": entry - atr * 5.0,
            "atr_14": atr,
            "timeframe": "1h",
        }
        frame = frame_trade("trend_long", 1, entry, features, atr=atr)
        # Should not be capped — structural stop preserved
        assert frame.stop < entry - atr * 4.5, f"stop {frame.stop} was incorrectly capped for 1h"


@pytest.mark.unit
class TestZoneValidation:
    """validate_stop_against_zone ensures stops are outside entry zones."""

    def test_long_stop_below_zone_passes(self):
        """Long: stop < zone_low is valid."""
        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        result = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=99.0, direction=1, atr=2.0
        )
        assert result == 99.0, "Valid stop should be returned unchanged"

    def test_long_stop_inside_zone_corrected(self):
        """Long: stop >= zone_low is corrected to zone_low - 2×ATR."""
        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        result = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=101.0, direction=1, atr=2.0
        )
        assert result == 96.0, "Stop should be corrected to zone_low - 2×ATR"

    def test_short_stop_above_zone_passes(self):
        """Short: stop > zone_high is valid."""
        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        result = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=106.0, direction=-1, atr=2.0
        )
        assert result == 106.0, "Valid stop should be returned unchanged"

    def test_short_stop_inside_zone_corrected(self):
        """Short: stop <= zone_high is corrected to zone_high + 2×ATR."""
        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        result = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=104.0, direction=-1, atr=2.0
        )
        assert result == 109.0, "Stop should be corrected to zone_high + 2×ATR"

    def test_stop_at_zone_edge_is_corrected(self):
        """Stop exactly at zone edge (within epsilon) is considered inside zone."""
        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        # Long: stop == zone_low - 1e-10 (inside due to floating point precision)
        result_long = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=100.0, direction=1, atr=2.0
        )
        assert result_long < 100.0, "Stop at zone_low edge should be corrected"

        # Short: stop == zone_high
        result_short = validate_stop_against_zone(
            zone_low=100.0, zone_high=105.0, stop_loss=105.0, direction=-1, atr=2.0
        )
        assert result_short > 105.0, "Stop at zone_high edge should be corrected"

    def test_no_atr_raises_value_error(self):
        """Stop inside zone without ATR raises ValueError."""
        import pytest

        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        with pytest.raises(ValueError, match="inside entry zone"):
            validate_stop_against_zone(
                zone_low=100.0, zone_high=105.0, stop_loss=101.0, direction=1, atr=None
            )

    def test_extreme_correction_raises_value_error(self):
        """Correction beyond 3×ATR distance raises ValueError."""
        import pytest

        from src.intelligence.trading.plugin_utils import validate_stop_against_zone

        # zone_low=100, stop=110 (10 points inside), atr=2 → correction would be 96
        # That's a 4-point correction distance, which is 2×ATR, so should pass
        # But if we set zone_low=100, stop=200 with atr=10, that's 100 points = 10×ATR
        with pytest.raises(ValueError, match="too extreme"):
            validate_stop_against_zone(
                zone_low=100.0, zone_high=105.0, stop_loss=200.0, direction=1, atr=10.0
            )

    def test_frame_trade_calls_zone_validation(self):
        """frame_trade() delegates to validate_stop_against_zone() for zone violations."""
        # This test verifies the integration: when stop would be inside zone,
        # frame_trade() calls validate_stop_against_zone() which logs and corrects
        features = {"atr_14": 5.0, "timeframe": "1m"}
        frame = frame_trade("test_long", 1, 450.0, features, atr=5.0)

        # After frame_trade() resolves zone and validates, stop should be outside zone
        assert frame.stop < frame.zone_low, "Long stop must be below zone_low"
        assert frame.viable, "Frame should be viable with corrected stop"
