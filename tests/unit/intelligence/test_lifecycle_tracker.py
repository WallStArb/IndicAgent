"""Tests for signal lifecycle tracker."""

from datetime import UTC, datetime, timedelta

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


def _pending_with_zone(direction=1, entry=5100.0, stop=5085.0,
                       zone_low=5095.0, zone_high=5105.0) -> dict:
    """Pending signal with zone bounds."""
    return {
        "signal_id": "test-id",
        "status": "pending",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": [5115.0, 5130.0, 5145.0] if direction == 1 else [5085.0, 5070.0, 5055.0],
        "ttl_bars": 10,
        "bars_elapsed": 0,
        "point_value": 50.0,
        "entry_zone_low": zone_low,
        "entry_zone_high": zone_high,
    }


@pytest.mark.unit
class TestZoneAwareActivation:
    def test_bar_overlaps_zone_activates_long(self):
        """Bar range overlaps zone: low <= zone_high AND high >= zone_low."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        t = evaluate_signal(sig, high=5098.0, low=5093.0, close=5096.0)
        assert t is not None
        assert t.new_status == "active"
        assert t.activation_price == 5098.0  # min(high, zone_high)

    def test_bar_entirely_above_zone_does_not_activate_long(self):
        """Bar entirely above the zone: no activation."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5100.0)
        t = evaluate_signal(sig, high=5115.0, low=5103.0, close=5110.0)
        assert t is None

    def test_zone_entry_pct_proximal(self):
        """Activation at proximal edge: zone_entry_pct near 0.0."""
        sig = _pending_with_zone(direction=1, zone_low=5090.0, zone_high=5100.0)
        # bar dips just into zone top (proximal for long = zone_high)
        t = evaluate_signal(sig, high=5101.0, low=5099.0, close=5100.0)
        assert t is not None
        assert t.zone_entry_pct is not None
        assert 0.0 <= t.zone_entry_pct <= 1.0


@pytest.mark.unit
class TestMAEMFE:
    def test_mfe_updates_on_favorable_move(self):
        """Active signal: favorable move, no exit yet."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5110.0, low=5098.0, close=5108.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is None  # no exit yet

    def test_mae_updates_on_adverse_move(self):
        """Active signal: adverse move doesn't hit stop yet."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5086.0,
                             targets=[5115.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # Price dips toward stop but doesn't hit it
        t = evaluate_signal(sig, high=5102.0, low=5088.0, close=5090.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is None  # stop not hit (low=5088 > stop=5086)


@pytest.mark.unit
class TestOutcomeClassification:
    def test_outcome_never_activated_on_ttl_expiry_pending(self):
        """Signal that TTL-expires while still pending → never_activated."""
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10  # hit TTL
        t = evaluate_signal(sig, high=5080.0, low=5075.0, close=5078.0)
        assert t is not None
        assert t.new_status == "expired"
        assert t.outcome == "never_activated"

    def test_outcome_target_1_on_t1_hit(self):
        """Active signal exits at T1 → outcome = target_1."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5120.0, low=5102.0, close=5118.0,
                            current_mae=0.0, current_mfe=0.5)
        assert t is not None
        assert t.new_status == "target_1_hit"
        assert t.outcome == "target_1"

    def test_outcome_stopped_in_trade_after_mfe(self):
        """Signal stopped out after having positive MFE → stopped_in_trade."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # MFE > 0.05 means price moved in favor at some point
        t = evaluate_signal(sig, high=5090.0, low=5084.0, close=5085.0,
                            current_mae=-0.1, current_mfe=0.8)
        assert t is not None
        assert t.new_status == "stopped_out"
        assert t.outcome == "stopped_in_trade"

    def test_outcome_stopped_at_entry_when_mfe_zero(self):
        """Signal stopped quickly (mfe near 0) → stopped_at_entry."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5085.0,
                            current_mae=0.0, current_mfe=0.0)
        assert t is not None
        assert t.outcome == "stopped_at_entry"


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
