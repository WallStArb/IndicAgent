"""Characterization tests for trade_framer emergency ATR fallback, stop cap, and
stop_basis classification.

These tests document and pin critical ML-label-generating behavior — do not
modify without understanding the data integrity implications.
"""

import pytest

from src.intelligence.trading.trade_framer import (
    ATR_EMERGENCY_FALLBACK_PCT,
    _classify_stop_basis,
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


@pytest.mark.unit
class TestStopCapLabel:
    """Stop cap must label the stop as 'atr_capped', NOT 'atr'.

    'atr_capped' means: a structural level was found but exceeded the per-TF stop cap,
    so ATR×2.0 was substituted. This is semantically distinct from 'atr' (no structure
    found at all). Conflating them corrupts ML training labels — the most dangerous error
    class per Renaissance data integrity principles.
    """

    def test_stop_cap_sets_atr_capped_not_atr(self):
        """When structural stop > 3×ATR on 1m, frame_trade must set stop_type='atr_capped'."""
        # 1m cap is 3.0×ATR.  swing_low at entry-20 = 4980; ATR=5; distance=20=4×ATR > 3×.
        # Resolver picks swing_low → stop=4980-5*0.25=4978.75 (distance=21.25 ATR > 3).
        features = {
            "timeframe": "1m",
            "swing_low": 4980.0,
            "nearest_resistance": 5030.0,
        }
        result = frame_trade("trend_long", 1, 5000.0, features, atr=5.0)
        assert result.stop_type == "atr_capped", (
            f"Expected 'atr_capped', got '{result.stop_type}'. "
            "Structural stop was capped — label must distinguish from pure ATR fallback."
        )
        # Corrected stop must be entry - 2.0×ATR (seed fallback value)
        assert result.stop == pytest.approx(5000.0 - 5.0 * 2.0, abs=0.01)

    def test_stop_cap_yields_atr_static_stop_basis(self):
        """Capped stop must produce stop_basis='atr_static', not 'garch_adaptive'."""
        features = {"timeframe": "1m", "swing_low": 4980.0, "nearest_resistance": 5030.0}
        result = frame_trade("trend_long", 1, 5000.0, features, atr=5.0)
        assert (
            result.stop_basis == "atr_static"
        ), f"stop_basis should be 'atr_static' for capped stop, got '{result.stop_basis}'"

    def test_pure_atr_fallback_still_labeled_atr(self):
        """Pure ATR fallback (no structural level at all) must still be 'atr', not 'atr_capped'."""
        # No structural features → resolver hits fallback branch
        features = {"timeframe": "1m", "nearest_resistance": 5020.0}
        result = frame_trade("trend_long", 1, 5000.0, features, atr=5.0)
        assert (
            result.stop_type == "atr"
        ), "Pure fallback (no structural level) must remain 'atr', not 'atr_capped'"


@pytest.mark.unit
class TestClassifyStopBasis:
    """_classify_stop_basis must return 'atr_static' for all ATR-family stop types.

    ML training segments on stop_basis. Returning 'garch_adaptive' for stops that
    are mechanically ATR-distance (atr_capped, zone_corrected) corrupts the segmentation.
    """

    def test_atr_stop_type_is_atr_static(self):
        basis, structure_type, dist = _classify_stop_basis("atr", 4990.0, 5000.0, 5.0, 1)
        assert basis == "atr_static"
        assert structure_type == "atr_fallback"
        assert dist == 0.0

    def test_atr_capped_is_atr_static(self):
        """atr_capped must not fall through to structural distance computation."""
        basis, structure_type, dist = _classify_stop_basis("atr_capped", 4990.0, 5000.0, 5.0, 1)
        assert basis == "atr_static"
        assert structure_type == "atr_fallback"
        assert dist == 0.0

    def test_zone_corrected_is_atr_static(self):
        """zone_corrected stop is ATR-distance from zone boundary — must not be 'garch_adaptive'."""
        basis, structure_type, dist = _classify_stop_basis("zone_corrected", 4990.0, 5000.0, 5.0, 1)
        assert basis == "atr_static"
        assert structure_type == "atr_fallback"
        assert dist == 0.0

    def test_swing_low_is_structural(self):
        """Sanity: genuine structural stop must not be mis-classified as atr_static."""
        basis, structure_type, dist = _classify_stop_basis("swing_low", 4992.0, 5000.0, 5.0, 1)
        assert basis in ("structure_snap", "garch_adaptive")
        assert structure_type == "swing_low"
