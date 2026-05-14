"""Tests for signal quality hardening: W1-W7."""

from src.core.service_utils import TF_TTL_BARS, TICK_SIZES, round_to_tick
from src.intelligence.trading.signal_schema import make_signal


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


class TestTickPrecisionRounding:
    """W3: make_signal uses tick precision instead of 2dp."""

    def test_fx_entry_price_rounded_to_pipette(self):
        sig = make_signal(
            symbol="EURUSD",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=1.169174,
            stop_loss=1.168500,
            targets=[1.170500],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )
        assert sig["entry_price"] == 1.16917
        assert sig["stop_loss"] == 1.16850
        assert sig["targets"][0] == 1.17050

    def test_unknown_symbol_preserves_precision(self):
        sig = make_signal(
            symbol="MYCOIN",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=0.000123456,
            stop_loss=0.000100000,
            targets=[0.000200000],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )
        assert sig["entry_price"] == 0.000123456
        assert sig["stop_loss"] == 0.000100000

    def test_index_future_rounded_to_quarter(self):
        sig = make_signal(
            symbol="ES",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=5432.67,
            stop_loss=5430.10,
            targets=[5440.30],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )
        assert sig["entry_price"] == 5432.75
        assert sig["stop_loss"] == 5430.0
        assert sig["targets"][0] == 5440.25


class TestTFTTLBars:
    """W1: TF-aware TTL bars wired into signal construction."""

    def test_tf_ttl_bars_has_all_timeframes(self):
        assert "1m" in TF_TTL_BARS
        assert "5m" in TF_TTL_BARS
        assert "15m" in TF_TTL_BARS
        assert "1h" in TF_TTL_BARS
        assert "4h" in TF_TTL_BARS
        assert "1d" in TF_TTL_BARS

    def test_make_signal_auto_computes_ttl_from_timeframe(self):
        sig = make_signal(
            symbol="EURUSD",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=1.10,
            stop_loss=1.09,
            targets=[1.12],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )
        assert sig["ttl_bars"] == TF_TTL_BARS["1m"]

    def test_make_signal_5m_ttl(self):
        sig = make_signal(
            symbol="EURUSD",
            timeframe="5m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=1.10,
            stop_loss=1.09,
            targets=[1.12],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )
        assert sig["ttl_bars"] == TF_TTL_BARS["5m"]

    def test_make_signal_explicit_ttl_overrides(self):
        sig = make_signal(
            symbol="EURUSD",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            entry_price=1.10,
            stop_loss=1.09,
            targets=[1.12],
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
            ttl_bars=99,
        )
        assert sig["ttl_bars"] == 99
