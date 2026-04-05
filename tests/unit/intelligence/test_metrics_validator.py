"""Tests for DataQualityValidator — all 4 gates."""
from src.intelligence.metrics.validator import validate_signal_row


class TestGate1Direction:
    def test_valid_long(self):
        r = validate_signal_row(1, 5000.0, 4999.0, 0.5, 1)
        assert r.is_valid is True

    def test_valid_short(self):
        r = validate_signal_row(-1, 5000.0, 5001.0, -0.5, 1)
        assert r.is_valid is True

    def test_zero_direction_invalid(self):
        r = validate_signal_row(0, 5000.0, 4999.0, 0.5, 1)
        assert r.is_valid is False
        assert r.reason_code == "invalid_direction"

    def test_none_direction_invalid(self):
        r = validate_signal_row(None, 5000.0, 4999.0, 0.5, 1)
        assert r.is_valid is False
        assert r.reason_code == "invalid_direction"


class TestGate2Risk:
    def test_valid_risk_one_tick(self):
        # ES: entry 5000.0, stop 4999.75 = 0.25 tick = exactly MIN_TICK_SIZE
        r = validate_signal_row(1, 5000.0, 4999.75, -0.5, 1)
        assert r.is_valid is True

    def test_risk_below_min_tick(self):
        # CVDDivergence bug: stop almost equal to entry
        r = validate_signal_row(1, 5000.0, 4999.974, -193.0, 1)
        assert r.is_valid is False
        assert r.reason_code == "risk_below_min_tick"

    def test_none_entry_invalid(self):
        r = validate_signal_row(1, None, 4999.0, 0.5, 1)
        assert r.is_valid is False
        assert r.reason_code == "risk_below_min_tick"

    def test_none_stop_invalid(self):
        r = validate_signal_row(1, 5000.0, None, 0.5, 1)
        assert r.is_valid is False
        assert r.reason_code == "risk_below_min_tick"


class TestGate3PnlR:
    def test_exactly_at_threshold_valid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, 10.0, 1)
        assert r.is_valid is True

    def test_above_threshold_invalid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, 10.001, 1)
        assert r.is_valid is False
        assert r.reason_code == "pnl_r_outlier"

    def test_large_negative_invalid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, -496.67, 1)
        assert r.is_valid is False
        assert r.reason_code == "pnl_r_outlier"

    def test_negative_at_threshold_valid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, -10.0, 1)
        assert r.is_valid is True


class TestGate4Regime:
    def test_missing_regime_invalid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, 0.5, None)
        assert r.is_valid is False
        assert r.reason_code == "missing_regime"

    def test_regime_zero_valid(self):
        r = validate_signal_row(1, 5000.0, 4999.0, 0.5, 0)
        assert r.is_valid is True


class TestNullPnlR:
    def test_null_pnl_r_is_valid_never_activated(self):
        # NULL pnl_r = zone never activated — valid, not a DQ failure
        r = validate_signal_row(1, 5000.0, 4999.0, None, 1)
        assert r.is_valid is True
        assert r.reason_code is None
