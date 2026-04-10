"""Tests for DataQualityValidator — all 4 gates + per-instrument tick sizes."""
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
    def test_valid_risk_one_tick_es(self):
        # ES: entry 5000.0, stop 4999.75 = 0.25 tick = exactly min tick
        r = validate_signal_row(1, 5000.0, 4999.75, -0.5, 1, symbol="ES", tick_sizes={"ES": 0.25})
        assert r.is_valid is True

    def test_risk_below_min_tick_es(self):
        # CVDDivergence bug: stop almost equal to entry (ES tick=0.25)
        r = validate_signal_row(1, 5000.0, 4999.974, -193.0, 1, symbol="ES", tick_sizes={"ES": 0.25})
        assert r.is_valid is False
        assert r.reason_code == "risk_below_min_tick"

    def test_forex_small_tick_valid(self):
        # EURUSD tick=0.0001, risk=0.0002 > 0.0001
        r = validate_signal_row(1, 1.1200, 1.1198, 0.5, 1, symbol="EURUSD", tick_sizes={"EUR": 0.0001})
        assert r.is_valid is True

    def test_forex_risk_below_tick(self):
        # EURUSD tick=0.0001, risk=0.00005 < 0.0001
        r = validate_signal_row(1, 1.1200, 1.11995, -10.0, 1, symbol="EURUSD", tick_sizes={"EUR": 0.0001})
        assert r.is_valid is False
        assert r.reason_code == "risk_below_min_tick"

    def test_bond_tick_size(self):
        # ZN (10y Treasury): tick = 1/64 = 0.015625
        r = validate_signal_row(1, 110.50, 110.484375, 0.5, 1, symbol="ZNM6", tick_sizes={"ZN": 0.015625})
        assert r.is_valid is True

    def test_copper_tick_size(self):
        # HG copper: tick = 0.0005, risk = 0.0006 > tick
        r = validate_signal_row(1, 5.5000, 5.4994, 0.5, 1, symbol="HG", tick_sizes={"HG": 0.0005})
        assert r.is_valid is True

    def test_default_tick_when_unknown_instrument(self):
        # Unknown instrument uses DEFAULT_MIN_TICK (0.01)
        r = validate_signal_row(1, 100.0, 99.99, 0.5, 1)
        assert r.is_valid is True

    def test_default_tick_rejects_zero_risk(self):
        r = validate_signal_row(1, 100.0, 100.0, 0.5, 1)
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

    def test_futures_base_symbol_resolution(self):
        # ESM6 should resolve to ES base symbol
        r = validate_signal_row(1, 5000.0, 4999.75, 0.5, 1, symbol="ESM6", tick_sizes={"ES": 0.25})
        assert r.is_valid is True


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
