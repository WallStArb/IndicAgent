"""Tests for signal quality hardening: W1-W7."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

_T0 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)

from src.core.service_utils import TF_TTL_BARS, TICK_SIZES, round_to_tick
from src.intelligence.trading.aggregator import _CONFIDENCE_BOOST_PER_AGREE
from src.intelligence.trading.lifecycle_tracker import evaluate_market_entry, evaluate_signal
from src.intelligence.trading.signal_schema import _make_signal as make_signal
from src.intelligence.trading.signal_schema import make_signal_from_frame
from src.persistence.repository.signal_ledger_repository import SignalStatus


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


def _make_viable_tf(
    entry=1.10, stop=1.09, targets=None, stop_type="atr", rr_t1=2.0, zone_low=None, zone_high=None
):
    """Build a mock TradeFrame that passes tf.viable."""
    tf = MagicMock()
    tf.viable = True
    tf.entry = entry
    tf.stop = stop
    tf.entry_type = "at_close"
    tf.stop_type = stop_type
    tf.method = "atr_fallback"
    tf.rr_t1 = rr_t1
    tf.rr_t2 = None
    tf.rr_t3 = None
    tf.zone_low = zone_low or entry
    tf.zone_high = zone_high or entry

    if targets is None:
        t = MagicMock()
        t.price = entry + abs(entry - stop) * 2.0
        t.label = "T1"
        t.level_type = "resistance"
        targets = [t]
    tf.targets = targets
    return tf


class TestEmissionGate:
    """W4: Emission gate rejects invalid signals."""

    def _make_signal(self, entry=1.10, stop=1.09, stop_type="atr"):
        tf = _make_viable_tf(entry=entry, stop=stop, stop_type=stop_type)
        return make_signal_from_frame(
            tf,
            symbol="EURUSD",
            timeframe="1m",
            timestamp="2026-01-01T00:00:00Z",
            signal_type="long",
            setup_plugin="test",
            direction=1,
            confidence=0.8,
            regime_context="any",
            confluence_score=0.5,
            supporting_factors=[],
            invalidation_conditions=[],
        )

    def test_accepts_valid_signal(self):
        sig = self._make_signal(entry=1.10, stop=1.09)
        assert sig is not None
        assert sig["entry_price"] > 0

    def test_rejects_stop_equals_entry(self):
        with pytest.raises(ValueError, match="stop.*tick"):
            self._make_signal(entry=1.10, stop=1.10)

    def test_rejects_stop_too_close_to_entry(self):
        # EURUSD tick = 0.00001, stop 0.000005 away (< tick)
        with pytest.raises(ValueError, match="stop.*tick"):
            self._make_signal(entry=1.10000, stop=1.099995)


class TestTTLReorder:
    """W2: TTL check runs AFTER stop/target, so price-at-target signals don't expire."""

    def _base_signal(self, status=SignalStatus.ACTIVE, bars_elapsed=20, ttl=20):
        return {
            "signal_id": "test-001",
            "status": status,
            "direction": 1,
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "targets": [104.0],
            "ttl_bars": ttl,
            "bars_elapsed": bars_elapsed,
            "point_value": 1.0,
            "entry_zone_low": 99.5,
            "entry_zone_high": 100.5,
        }

    def test_target_hit_on_ttl_bar_takes_target_not_ttl(self):
        # T1 no longer exits; use a signal with T2 so a target exit still fires.
        # The invariant under test is: price-at-target beats TTL expiry on the same bar.
        sig = self._base_signal(bars_elapsed=20, ttl=20)
        sig["targets"] = [104.0, 108.0]  # add T2 so a target exit is possible
        sig["expires_at"] = _T0 + timedelta(minutes=20)
        bar_time = _T0 + timedelta(minutes=20)  # exactly at TTL boundary
        result = evaluate_signal(sig, high=109.0, low=99.0, close=107.0, bar_time=bar_time)
        assert result is not None
        assert result.exit_reason == "target_2_hit"  # target_hit beats TTL

    def test_stop_on_ttl_bar_takes_stop_not_ttl(self):
        sig = self._base_signal(bars_elapsed=20, ttl=20)
        result = evaluate_signal(sig, high=101.0, low=97.0, close=97.5)
        assert result is not None
        assert result.exit_reason == "stop_loss"

    def test_ttl_expired_when_no_hit(self):
        sig = self._base_signal(bars_elapsed=20, ttl=20)
        # expires_at = T0 + 20 bars * 60s; bar_time = T0 + 21min → past expires_at
        sig["expires_at"] = _T0 + timedelta(minutes=20)
        bar_time = _T0 + timedelta(minutes=21)
        result = evaluate_signal(sig, high=101.0, low=99.5, close=100.5, bar_time=bar_time)
        assert result is not None
        assert result.exit_reason == "ttl_expired"


class TestMarketEntryTTLReorder:
    """W2: evaluate_market_entry also checks stop/target before TTL."""

    def _base_signal(self, bars_elapsed=20, ttl=20):
        return {
            "signal_id": "test-mkt-001",
            "direction": 1,
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "targets": [104.0],
            "ttl_bars": ttl,
            "bars_elapsed": bars_elapsed,
        }

    def test_target_hit_on_ttl_bar(self):
        sig = self._base_signal(bars_elapsed=20, ttl=20)
        result = evaluate_market_entry(
            sig, market_entry_price=100.0, high=105.0, low=99.0, close=103.0
        )
        assert result.outcome is not None
        assert result.exit_price == 104.0

    def test_ttl_expired_when_no_hit(self):
        sig = self._base_signal(bars_elapsed=20, ttl=20)
        result = evaluate_market_entry(
            sig, market_entry_price=100.0, high=101.0, low=99.5, close=100.5
        )
        assert result.outcome is not None
        assert result.exit_price == 100.5


class TestNoConfidenceBoost:
    """W7: Confidence boost per agreeing signal is removed."""

    def test_confidence_boost_constant_is_zero(self):
        assert _CONFIDENCE_BOOST_PER_AGREE == 0.0
