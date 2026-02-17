"""Tests for signal lifecycle tracker."""

import pytest

from src.intelligence.trading.lifecycle_tracker import (
    evaluate_signal,
)


def _pending_signal(direction=1, entry=5100.0, stop=5085.0,
                    targets=None) -> dict:
    """Build a pending signal dict for lifecycle testing."""
    return {
        "signal_id": "test-id",
        "status": "pending",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": targets or [5115.0, 5130.0, 5145.0],
        "ttl_bars": 10,
        "bars_elapsed": 0,
        "point_value": 50.0,
    }


def _active_signal(direction=1, entry=5100.0, stop=5085.0,
                   targets=None) -> dict:
    sig = _pending_signal(direction, entry, stop, targets)
    sig["status"] = "active"
    return sig


class TestPendingToActive:
    @pytest.mark.unit
    def test_price_crosses_entry_long(self):
        """Long signal: high >= entry_price -> activate."""
        sig = _pending_signal(direction=1, entry=5100.0)
        t = evaluate_signal(sig, high=5101.0, low=5095.0, close=5100.5)
        assert t is not None
        assert t.new_status == "active"
        assert t.exit_reason is None

    @pytest.mark.unit
    def test_price_below_entry_long_stays_pending(self):
        """Long signal: high < entry_price -> stays pending."""
        sig = _pending_signal(direction=1, entry=5100.0)
        t = evaluate_signal(sig, high=5098.0, low=5090.0, close=5095.0)
        assert t is None

    @pytest.mark.unit
    def test_price_crosses_entry_short(self):
        """Short signal: low <= entry_price -> activate."""
        sig = _pending_signal(direction=-1, entry=5100.0, stop=5115.0,
                              targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5105.0, low=5099.0, close=5100.0)
        assert t is not None
        assert t.new_status == "active"


class TestActiveToExit:
    @pytest.mark.unit
    def test_stop_loss_hit_long(self):
        """Long active: low <= stop_loss -> stopped_out."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5085.0

    @pytest.mark.unit
    def test_stop_loss_hit_short(self):
        """Short active: high >= stop_loss -> stopped_out."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0,
                             targets=[5085.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_1_hit_long(self):
        """Long active: high >= target[0] -> target_1_hit."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_2_hit_long(self):
        """Long active: high >= target[1] -> target_2_hit."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_signal(sig, high=5131.0, low=5120.0, close=5129.0)
        assert t.new_status == "target_2_hit"
        assert t.exit_reason == "target_2"

    @pytest.mark.unit
    def test_target_hit_short(self):
        """Short active: low <= target[0] -> target_1_hit."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0,
                             targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5085.0

    @pytest.mark.unit
    def test_stop_checked_before_target(self):
        """If both stop and target hit on same bar, stop takes priority."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0])
        t = evaluate_signal(sig, high=5116.0, low=5084.0, close=5090.0)
        assert t.new_status == "stopped_out"
        assert t.exit_reason == "stop_loss"


class TestTTLExpiry:
    @pytest.mark.unit
    def test_pending_expires_after_ttl(self):
        """Pending signal past ttl_bars -> expired."""
        sig = _pending_signal()
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5095.0, low=5090.0, close=5092.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "ttl_expired"

    @pytest.mark.unit
    def test_active_expires_after_ttl(self):
        """Active signal past ttl_bars -> expired."""
        sig = _active_signal()
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5098.0, low=5095.0, close=5097.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "ttl_expired"


class TestPnLCalculation:
    @pytest.mark.unit
    def test_pnl_on_stop_long(self):
        """PnL calculated correctly for stopped long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.pnl_ticks == pytest.approx(-15.0)
        assert t.pnl_r == pytest.approx(-1.0)
        assert t.pnl_dollars == pytest.approx(-750.0)

    @pytest.mark.unit
    def test_pnl_on_target_long(self):
        """PnL calculated correctly for target hit long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.pnl_ticks == pytest.approx(15.0)
        assert t.pnl_r == pytest.approx(1.0)
        assert t.pnl_dollars == pytest.approx(750.0)

    @pytest.mark.unit
    def test_pnl_on_expired_uses_close(self):
        """Expired signal uses close as exit price."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5108.0, low=5095.0, close=5105.0)
        assert t.exit_price == 5105.0
        assert t.pnl_ticks == pytest.approx(5.0)
