"""Tests for signal quality hardening: W1-W7."""

from src.core.service_utils import TICK_SIZES, round_to_tick


class TestTickSizes:
    """W3: Tick-precision rounding."""

    def test_fx_pair_rounds_to_pipette(self):
        result = round_to_tick(1.169174, "EURUSD")
        assert result == 1.16917

    def test_jpy_pair_rounds_to_thousandth(self):
        result = round_to_tick(149.1236, "USDJPY")
        assert result == 149.124

    def test_index_future_rounds_to_quarter(self):
        result = round_to_tick(5432.67, "ES")
        assert result == 5432.75

    def test_equity_rounds_to_cent(self):
        result = round_to_tick(153.456, "AAPL")
        assert result == 153.46

    def test_unknown_symbol_preserves_precision(self):
        result = round_to_tick(123.456789, "UNKNOWN")
        assert result == 123.456789

    def test_tick_sizes_has_required_entries(self):
        assert "EURUSD" in TICK_SIZES
        assert "ES" in TICK_SIZES
        assert "ZN" in TICK_SIZES
        assert "CL" in TICK_SIZES

    def test_round_to_tick_zero_price(self):
        result = round_to_tick(0.0, "EURUSD")
        assert result == 0.0
