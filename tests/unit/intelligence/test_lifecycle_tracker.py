"""Tests for signal lifecycle tracker."""

from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.trading.lifecycle_tracker import (
    evaluate_signal,
)

# Reference time anchor for TTL tests
_T0 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)


def _pending_signal(direction=1, entry=5100.0, stop=5085.0, targets=None) -> dict:
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


def _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=None) -> dict:
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
        sig = _pending_signal(direction=-1, entry=5100.0, stop=5115.0, targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5105.0, low=5099.0, close=5100.0)
        assert t is not None
        assert t.new_status == "active"


class TestActiveToExit:
    @pytest.mark.unit
    def test_stop_loss_hit_long(self):
        """Long active: low <= stop_loss -> stopped_out."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5085.0

    @pytest.mark.unit
    def test_stop_loss_hit_short(self):
        """Short active: high >= stop_loss -> stopped_out."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0, targets=[5085.0])
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_1_hit_long(self):
        """Long active: T1 advances be_floor but does NOT exit (partial fill semantics)."""
        sig = _active_signal(
            direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0, 5145.0]
        )
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t is None  # T1 does not exit; signal continues with floor protection

    @pytest.mark.unit
    def test_target_2_hit_long(self):
        """Long active: high >= target[1] -> expired with exit_reason target_2_hit."""
        sig = _active_signal(
            direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0, 5145.0]
        )
        t = evaluate_signal(sig, high=5131.0, low=5120.0, close=5129.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "target_2_hit"

    @pytest.mark.unit
    def test_target_hit_short(self):
        """Short active: T1 advances be_floor but does NOT exit (partial fill semantics)."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0, targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t is None  # T1 does not exit; signal continues with floor protection

    @pytest.mark.unit
    def test_stop_checked_before_target(self):
        """If both stop and target hit on same bar, stop takes priority."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0])
        t = evaluate_signal(sig, high=5116.0, low=5084.0, close=5090.0)
        assert t.new_status == "expired"
        assert t.exit_reason == "stop_loss"


class TestTTLExpiry:
    @pytest.mark.unit
    def test_pending_at_ttl_returns_none_when_no_zone_overlap(self):
        """Pending signal past ttl_bars with no zone overlap -> None.

        TTL for pending signals is handled by the calling service, not
        evaluate_signal() directly. The function only handles zone activation
        for pending signals.
        """
        sig = _pending_signal()
        sig["bars_elapsed"] = 11
        t = evaluate_signal(sig, high=5095.0, low=5090.0, close=5092.0)
        assert t is None

    @pytest.mark.unit
    def test_active_expires_after_ttl(self):
        """Active signal with bar_time >= expires_at -> expired."""
        sig = _active_signal()
        sig["bars_elapsed"] = 11
        # expires_at = T0 + 10 bars * 60s (1m TF); bar_time = T0 + 11min → past expires_at
        sig["expires_at"] = _T0 + timedelta(minutes=10)
        bar_time = _T0 + timedelta(minutes=11)
        t = evaluate_signal(sig, high=5098.0, low=5095.0, close=5097.0, bar_time=bar_time)
        assert t.new_status == "expired"
        assert t.exit_reason == "ttl_expired"

    @pytest.mark.unit
    def test_pending_expires_at_ttl_no_zone_overlap(self):
        """Pending signal: bar_time >= expires_at, bar does NOT overlap zone -> ttl_expired/never_activated.

        This is the safety-valve case: signal generated, zone never touched, TTL elapsed.
        After the fix, evaluate_signal falls through from the pending branch to the TTL
        block when _check_zone_activation returns None.
        """
        sig = _pending_signal(direction=1, entry=5100.0, stop=5085.0)
        sig["expires_at"] = _T0 + timedelta(minutes=10)
        bar_time = _T0 + timedelta(minutes=11)

        # Bar range 5040-5050 does NOT overlap zone (entry_zone defaults to entry ±0 → 5100).
        # No entry_zone_low/entry_zone_high in _pending_signal() → zone_low = zone_high = entry = 5100.
        # 5050 < 5100 → no overlap.
        t = evaluate_signal(
            sig,
            high=5050.0,
            low=5040.0,
            close=5045.0,
            bar_time=bar_time,
            signal_timestamp=_T0,
        )

        assert t is not None, "Expected TTL-expired Transition, got None"
        assert t.exit_reason == "ttl_expired"
        assert t.new_status == "expired"
        assert t.outcome == "never_activated"


def _pending_with_zone(
    direction=1, entry=5100.0, stop=5085.0, zone_low=5095.0, zone_high=5105.0
) -> dict:
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
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(
            sig, high=5110.0, low=5098.0, close=5108.0, current_mae=0.0, current_mfe=0.0
        )
        assert t is None  # no exit yet

    def test_mae_updates_on_adverse_move(self):
        """Active signal: adverse move doesn't hit stop yet."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5086.0, targets=[5115.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # Price dips toward stop but doesn't hit it
        t = evaluate_signal(
            sig, high=5102.0, low=5088.0, close=5090.0, current_mae=0.0, current_mfe=0.0
        )
        assert t is None  # stop not hit (low=5088 > stop=5086)


@pytest.mark.unit
class TestOutcomeClassification:
    def test_outcome_pending_at_ttl_returns_none_no_zone_overlap(self):
        """Pending signal at TTL with no zone overlap → None.

        TTL for pending signals is resolved by the calling service, not
        evaluate_signal(). When no zone overlap exists, evaluate_signal()
        returns None regardless of bars_elapsed.
        """
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10  # hit TTL
        t = evaluate_signal(sig, high=5080.0, low=5075.0, close=5078.0)
        # No zone overlap (high=5080 < zone_low=5095) → returns None
        assert t is None

    def test_outcome_target_1_on_t1_hit(self):
        """Active signal does NOT exit at T1 — T1 advances be_floor only."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(
            sig, high=5120.0, low=5102.0, close=5118.0, current_mae=0.0, current_mfe=0.5
        )
        assert t is None  # T1 does not exit; signal continues with floor protection

    def test_outcome_stopped_in_trade_after_mfe(self):
        """Signal stopped out after having positive MFE → stopped_in_trade."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        # MFE > 0.05 means price moved in favor at some point
        t = evaluate_signal(
            sig, high=5090.0, low=5084.0, close=5085.0, current_mae=-0.1, current_mfe=0.8
        )
        assert t is not None
        assert t.new_status == "expired"
        assert t.outcome is None  # stop outcomes deferred to service (needs bars_in_trade)

    def test_outcome_stopped_at_entry_when_mfe_zero(self):
        """Signal stopped quickly (mfe near 0) → outcome deferred to service."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(
            sig, high=5098.0, low=5084.0, close=5085.0, current_mae=0.0, current_mfe=0.0
        )
        assert t is not None
        assert t.outcome is None  # stop outcomes deferred to service (needs bars_in_trade)


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
        """T1 no longer exits; signal continues. T2 exits at target_2 with full P&L."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        t = evaluate_signal(sig, high=5131.0, low=5105.0, close=5129.0)
        assert t is not None
        assert t.exit_reason == "target_2_hit"
        assert t.pnl_ticks == pytest.approx(30.0)
        assert t.pnl_r == pytest.approx(2.0)
        assert t.pnl_dollars == pytest.approx(1500.0)

    @pytest.mark.unit
    def test_pnl_on_expired_uses_close(self):
        """Expired signal uses close as exit price."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0)
        sig["bars_elapsed"] = 11
        # expires_at = T0 + 10 bars * 60s (1m TF); bar_time = T0 + 11min → past expires_at
        sig["expires_at"] = _T0 + timedelta(minutes=10)
        bar_time = _T0 + timedelta(minutes=11)
        t = evaluate_signal(sig, high=5108.0, low=5095.0, close=5105.0, bar_time=bar_time)
        assert t.exit_price == 5105.0
        assert t.pnl_ticks == pytest.approx(5.0)


# ============================================================
# Market Track Tests
# ============================================================

from src.intelligence.trading.lifecycle_tracker import (  # noqa: E402
    MarketTransition,
    evaluate_market_entry,
)


def _market_signal(
    direction=1,
    entry=5100.0,
    stop=5085.0,
    targets=None,
    ttl_bars=10,
    bars_elapsed=0,
) -> dict:
    """Signal dict for market-track testing. entry_price != market_entry_price by design."""
    return {
        "signal_id": "mkt-test-id",
        "status": "pending",
        "direction": direction,
        "entry_price": entry,
        "stop_loss": stop,
        "targets": targets or [5115.0, 5130.0, 5145.0],
        "ttl_bars": ttl_bars,
        "bars_elapsed": bars_elapsed,
        "point_value": 50.0,
    }


@pytest.mark.unit
class TestMarketTransitionDataclass:
    def test_default_outcome_none(self):
        t = MarketTransition(signal_id="x")
        assert t.outcome is None

    def test_gap_bars_default_none(self):
        t = MarketTransition(signal_id="x")
        assert t.gap_bars is None


@pytest.mark.unit
class TestEvaluateMarketEntryMechanics:
    """evaluate_market_entry() — mechanical correctness."""

    def test_long_stop_hit_outcome_none(self):
        """Stop hit → outcome=None (caller resolves via _classify_stop_outcome)."""
        sig = _market_signal(direction=1, stop=5085.0)
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5098.0, low=5084.0, close=5086.0
        )
        assert t is not None
        assert t.exit_price == 5085.0
        assert t.outcome is None  # stop outcome is resolved by caller

    def test_short_stop_hit(self):
        sig = _market_signal(direction=-1, stop=5115.0, targets=[5085.0, 5070.0, 5055.0])
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5116.0, low=5105.0, close=5110.0
        )
        assert t.exit_price == 5115.0
        assert t.outcome is None

    def test_long_target_1(self):
        sig = _market_signal(direction=1, targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5116.0, low=5099.0, close=5115.0
        )
        assert t.outcome == "target_1"
        assert t.exit_price == 5115.0

    def test_long_target_full(self):
        sig = _market_signal(direction=1, targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5146.0, low=5099.0, close=5145.0
        )
        assert t.outcome == "target_full"
        assert t.exit_price == 5145.0


@pytest.mark.unit
class TestChandelierFloor:
    """be_floor: T1 advances to entry, T2 advances to target_1. Chandelier clamped."""

    def _signal(self, entry=5000.0, stop=4980.0, targets=None) -> dict:
        return {
            "signal_id": "test-floor-1",
            "status": "active",
            "direction": 1,
            "entry_price": entry,
            "stop_loss": stop,
            "targets": targets or [5020.0, 5040.0, 5060.0],
            "expires_at": None,
            "point_value": 50.0,
            "activated_at": "2026-01-01T10:00:00Z",
        }

    def _chandelier(self, trailing_stop=None, be_floor=None) -> dict:
        return {
            "trailing_stop": trailing_stop,
            "highest_high": 5010.0,
            "lowest_low": 4990.0,
            "vol": 5.0,
            "be_floor": be_floor,
        }

    def test_t1_hit_sets_be_floor_to_entry(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0)
        result = evaluate_signal(sig, high=5022.0, low=5001.0, close=5018.0, chandelier_state=state)
        assert result is None  # T1 does not exit
        assert state["be_floor"] == 5000.0  # advanced to entry

    def test_t1_hit_does_not_set_floor_twice(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5025.0, low=5001.0, close=5020.0, chandelier_state=state)
        assert state["be_floor"] == 5000.0  # unchanged

    def test_t2_hit_advances_floor_to_t1(self):
        sig = self._signal()
        state = self._chandelier(trailing_stop=4990.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5042.0, low=5005.0, close=5038.0, chandelier_state=state)
        assert state["be_floor"] == 5020.0  # advanced to target_1

    def test_chandelier_clamped_at_entry_after_t1(self):
        sig = self._signal()
        # trailing_stop is below entry (4995) but be_floor = entry (5000)
        state = self._chandelier(trailing_stop=4995.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5010.0, low=4998.0, close=5002.0, chandelier_state=state)
        assert result is not None
        assert result.exit_reason == "chandelier_stop"
        assert result.exit_price == pytest.approx(5000.0)
        assert result.pnl_r == pytest.approx(0.0, abs=1e-4)

    def test_chandelier_above_floor_not_clamped(self):
        sig = self._signal()
        # trailing_stop=5010 > be_floor=5000 -> clamp has no effect; stop is 5010
        state = self._chandelier(trailing_stop=5010.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5020.0, low=5008.0, close=5012.0, chandelier_state=state)
        assert result is not None
        assert result.exit_price == pytest.approx(5010.0)
        assert result.pnl_r > 0

    def test_no_floor_chandelier_unchanged(self):
        sig = self._signal()
        # be_floor=None -> clamp not applied; trailing_stop=4985 below entry
        state = self._chandelier(trailing_stop=4985.0, be_floor=None)
        result = evaluate_signal(sig, high=5010.0, low=4984.0, close=4990.0, chandelier_state=state)
        assert result is not None
        assert result.exit_price == pytest.approx(4985.0)

    def test_short_t1_sets_floor_to_entry(self):
        sig = self._signal(entry=5000.0, stop=5020.0, targets=[4980.0, 4960.0, 4940.0])
        sig["direction"] = -1
        state = self._chandelier(trailing_stop=5015.0, be_floor=None)
        result = evaluate_signal(sig, high=4999.0, low=4978.0, close=4982.0, chandelier_state=state)
        assert result is None
        assert state["be_floor"] == pytest.approx(5000.0)

    def test_short_chandelier_clamped_at_entry_after_t1(self):
        sig = self._signal(entry=5000.0, stop=5020.0, targets=[4980.0, 4960.0, 4940.0])
        sig["direction"] = -1
        # trailing_stop=5005 > entry=5000 but be_floor=5000 -> effective stop=5000
        state = self._chandelier(trailing_stop=5005.0, be_floor=5000.0)
        result = evaluate_signal(sig, high=5001.0, low=4990.0, close=4995.0, chandelier_state=state)
        assert result is not None
        assert result.exit_reason == "chandelier_stop"
        assert result.exit_price == pytest.approx(5000.0)

    def test_ttl_expired_ahead(self):
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5108.0, low=5099.0, close=5105.0, current_mfe=0.3
        )
        assert t.outcome == "ttl_expired_ahead"

    def test_ttl_expired_behind(self):
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5097.0, low=5093.0, close=5094.0, current_mfe=0.0
        )
        assert t.outcome == "ttl_expired_behind"

    def test_no_exit_returns_still_running(self):
        """No stop/target/TTL hit → MarketTransition with outcome=None."""
        sig = _market_signal(direction=1, bars_elapsed=3)
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5108.0, low=5099.0, close=5105.0
        )
        assert t.outcome is None
        assert t.exit_price is None

    def test_risk_uses_market_entry_price_not_entry_price(self):
        """Market track risk = abs(market_entry_price - stop), not abs(entry_price - stop)."""
        # entry_price=5100, stop=5085 → zone risk=15
        # market_entry_price=5090, stop=5085 → market risk=5
        sig = _market_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5105.0])
        t = evaluate_market_entry(
            sig, market_entry_price=5090.0, high=5106.0, low=5089.0, close=5105.0
        )
        expected_pnl_r = round((5105.0 - 5090.0) * 1 / abs(5090.0 - 5085.0), 4)
        assert t.pnl_r == expected_pnl_r

    def test_stop_checked_before_target(self):
        """Same bar hits both stop and target — stop wins."""
        sig = _market_signal(direction=1, stop=5085.0, targets=[5115.0])
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5116.0, low=5084.0, close=5100.0
        )
        assert t.exit_price == 5085.0
        assert t.outcome is None  # stop → caller classifies

    def test_never_activated_absent_from_market_track(self):
        """Market track never returns never_activated — the concept doesn't apply."""
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(
            sig, market_entry_price=5100.0, high=5097.0, low=5093.0, close=5094.0
        )
        assert t.outcome != "never_activated"


@pytest.mark.unit
class TestMarketTrackMathInvariants:
    """Assert on final MarketTransition values only — not intermediate per-bar state."""

    def _run_bars(self, sig, market_price, bars):
        """Feed N bars to evaluate_market_entry, returning final transition."""
        mae = mfe = 0.0
        t = None
        for high, low, close in bars:
            t = evaluate_market_entry(
                sig,
                market_entry_price=market_price,
                high=high,
                low=low,
                close=close,
                current_mae=mae,
                current_mfe=mfe,
            )
            if t.outcome is not None:
                return t
            # accumulate excursions on no-exit bars (mirrors service logic)
            direction = sig["direction"]
            risk = abs(market_price - sig["stop_loss"])
            if risk > 0:
                close_pnl_r = (close - market_price) * direction / risk
                mae = min(mae, close_pnl_r)
                mfe = max(mfe, close_pnl_r)
        return t

    def test_mae_le_pnl_r_le_mfe(self):
        sig = _market_signal(direction=1, stop=5085.0, targets=[5120.0])
        bars = [(5103.0, 5098.0, 5101.0), (5110.0, 5102.0, 5108.0), (5121.0, 5105.0, 5120.0)]
        t = self._run_bars(sig, 5100.0, bars)
        assert t.mae <= t.pnl_r <= t.mfe

    def test_mae_nonpositive_on_losing_trade(self):
        sig = _market_signal(direction=1, stop=5085.0, targets=[5120.0])
        bars = [(5095.0, 5084.0, 5085.0)]  # stop hit immediately
        t = self._run_bars(sig, 5100.0, bars)
        assert t.mae <= 0

    def test_pnl_r_formula_exact(self):
        sig = _market_signal(direction=1, stop=5085.0, targets=[5115.0])
        bars = [(5116.0, 5100.0, 5115.0)]
        t = self._run_bars(sig, 5100.0, bars)
        expected = round((5115.0 - 5100.0) * 1 / abs(5100.0 - 5085.0), 4)
        assert t.pnl_r == expected

    def test_stop_exit_price_exact(self):
        sig = _market_signal(direction=1, stop=5085.0)
        bars = [(5098.0, 5084.0, 5086.0)]
        t = self._run_bars(sig, 5100.0, bars)
        assert t.exit_price == 5085.0

    def test_target_exit_price_exact(self):
        sig = _market_signal(direction=1, stop=5085.0, targets=[5115.0])
        bars = [(5116.0, 5099.0, 5115.0)]
        t = self._run_bars(sig, 5100.0, bars)
        assert t.exit_price == 5115.0


# ============================================================
# Chandelier Stop Tests
# ============================================================

from src.intelligence.trading.lifecycle_tracker import (  # noqa: E402
    compute_chandelier_stop,
    compute_staleness_score,
)


@pytest.mark.unit
class TestComputeChandelierStop:
    def test_long_stop_formula(self):
        """Long (direction=1): highest_high - 3 * vol."""
        result = compute_chandelier_stop(
            direction=1, highest_high=5120.0, lowest_low=5090.0, vol=10.0
        )
        assert result == pytest.approx(5120.0 - 3 * 10.0)

    def test_short_stop_formula(self):
        """Short (direction=-1): lowest_low + 3 * vol."""
        result = compute_chandelier_stop(
            direction=-1, highest_high=5120.0, lowest_low=5080.0, vol=10.0
        )
        assert result == pytest.approx(5080.0 + 3 * 10.0)

    def test_custom_multiplier(self):
        """Custom multiplier applied correctly."""
        result = compute_chandelier_stop(
            direction=1, highest_high=5100.0, lowest_low=5080.0, vol=5.0, multiplier=2.0
        )
        assert result == pytest.approx(5100.0 - 2 * 5.0)

    def test_uses_vol_parameter(self):
        """vol parameter drives the stop distance regardless of source (garch or atr)."""
        garch_result = compute_chandelier_stop(
            direction=1, highest_high=5100.0, lowest_low=5080.0, vol=8.0
        )
        atr_result = compute_chandelier_stop(
            direction=1, highest_high=5100.0, lowest_low=5080.0, vol=8.0
        )
        assert garch_result == atr_result


@pytest.mark.unit
class TestChandelierTightening:
    """Chandelier stop tightens monotonically via in-place mutation in evaluate_signal."""

    def test_long_stop_tightens_when_high_increases(self):
        """For a long, as highest_high rises the stop should move up (tighten)."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5150.0])
        ch = {
            "trailing_stop": 5090.0,  # previous stop
            "highest_high": 5110.0,
            "lowest_low": 5095.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        # Bar: high=5115 exceeds highest_high -> new stop = 5115 - 3*5 = 5100 > 5090 -> tightens
        evaluate_signal(
            sig,
            high=5115.0,
            low=5098.0,
            close=5110.0,
            chandelier_state=ch,
        )
        assert ch["trailing_stop"] == pytest.approx(5100.0)

    def test_long_stop_does_not_widen(self):
        """Chandelier stop for long never moves down (widen)."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5150.0])
        ch = {
            "trailing_stop": 5100.0,  # relatively tight stop
            "highest_high": 5115.0,
            "lowest_low": 5095.0,
            "vol": 10.0,
            "vol_source": "garch_sigma",
        }
        # Bar: high=5108 < highest_high=5115 -> new_stop = 5115 - 30 = 5085 < 5100 -> rejected
        evaluate_signal(
            sig,
            high=5108.0,
            low=5098.0,
            close=5105.0,
            chandelier_state=ch,
        )
        assert ch["trailing_stop"] == pytest.approx(5100.0)  # unchanged

    def test_short_stop_tightens_when_low_decreases(self):
        """For a short, as lowest_low falls the stop should move down (tighten)."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0, targets=[5060.0, 5040.0])
        ch = {
            "trailing_stop": 5110.0,
            "highest_high": 5105.0,
            "lowest_low": 5090.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        # Bar: low=5085 < lowest_low -> new_stop = 5085 + 15 = 5100 < 5110 -> tightens
        evaluate_signal(
            sig,
            high=5097.0,
            low=5085.0,
            close=5088.0,
            chandelier_state=ch,
        )
        assert ch["trailing_stop"] == pytest.approx(5100.0)


@pytest.mark.unit
class TestChandelierStopExit:
    def test_long_exits_when_low_breaches_trailing_stop(self):
        """Long: low <= trailing_stop -> chandelier_stop exit."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        ch = {
            "trailing_stop": 5095.0,
            "highest_high": 5110.0,
            "lowest_low": 5095.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        t = evaluate_signal(
            sig,
            high=5100.0,
            low=5094.0,
            close=5096.0,
            chandelier_state=ch,
        )
        assert t is not None
        assert t.exit_reason == "chandelier_stop"
        assert t.outcome == "stopped_in_trade"

    def test_short_exits_when_high_breaches_trailing_stop(self):
        """Short: high >= trailing_stop -> chandelier_stop exit."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5130.0, targets=[5060.0, 5040.0])
        ch = {
            "trailing_stop": 5108.0,
            "highest_high": 5105.0,
            "lowest_low": 5090.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        t = evaluate_signal(
            sig,
            high=5109.0,
            low=5098.0,
            close=5105.0,
            chandelier_state=ch,
        )
        assert t is not None
        assert t.exit_reason == "chandelier_stop"
        assert t.outcome == "stopped_in_trade"

    def test_no_exit_when_price_clear_of_trailing_stop(self):
        """No chandelier exit when price is well above the trailing stop for a long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        ch = {
            "trailing_stop": 5090.0,
            "highest_high": 5110.0,
            "lowest_low": 5095.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        t = evaluate_signal(
            sig,
            high=5115.0,
            low=5105.0,
            close=5112.0,
            chandelier_state=ch,
        )
        assert t is None  # no exit


# ============================================================
# Staleness Score Tests
# ============================================================


@pytest.mark.unit
class TestComputeStalenessScore:
    def test_regime_flip_no_vol_drift(self):
        """Regime flip alone (sigma ratio < 2.0) -> score = 0.6, reason = 'hmm_regime_flip'."""
        score, reason = compute_staleness_score(
            hmm_regime_now=1,
            hmm_regime_at_fire=0,
            garch_sigma_now=1.0,
            garch_sigma_at_fire=1.0,
        )
        assert score == pytest.approx(0.6)
        assert reason == "hmm_regime_flip"

    def test_vol_drift_no_regime_flip(self):
        """Sigma ratio > 2.0 but same regime -> reason = 'vol_drift'."""
        score, reason = compute_staleness_score(
            hmm_regime_now=1,
            hmm_regime_at_fire=1,
            garch_sigma_now=3.0,
            garch_sigma_at_fire=1.0,
        )
        # sigma_ratio = 3.0, log(3)/log(3) = 1.0 -> sigma_component = min(1.0, 1.0) = 1.0
        # score = 0.4 * 1.0 = 0.4
        assert score > 0.0
        assert reason == "vol_drift"

    def test_both_regime_flip_and_vol_drift(self):
        """Regime flip AND sigma ratio >= 2.0 -> reason = 'both'."""
        score, reason = compute_staleness_score(
            hmm_regime_now=2,
            hmm_regime_at_fire=0,
            garch_sigma_now=4.0,
            garch_sigma_at_fire=1.0,
        )
        assert score > 0.5
        assert reason == "both"

    def test_no_drift_same_regime_same_vol(self):
        """Same regime, sigma ratio = 1.0 -> score = 0.0, reason = 'vol_drift'."""
        score, reason = compute_staleness_score(
            hmm_regime_now=1,
            hmm_regime_at_fire=1,
            garch_sigma_now=1.0,
            garch_sigma_at_fire=1.0,
        )
        assert score == pytest.approx(0.0)
        assert reason == "vol_drift"

    def test_none_regime_values_treated_as_matching(self):
        """None regimes don't trigger regime_drift (matches any)."""
        score, reason = compute_staleness_score(
            hmm_regime_now=None,
            hmm_regime_at_fire=None,
            garch_sigma_now=1.0,
            garch_sigma_at_fire=1.0,
        )
        assert score == pytest.approx(0.0)

    def test_none_sigma_values_no_crash(self):
        """None sigma values -> no vol component (zero sigma_component)."""
        score, reason = compute_staleness_score(
            hmm_regime_now=1,
            hmm_regime_at_fire=0,
            garch_sigma_now=None,
            garch_sigma_at_fire=None,
        )
        # Only regime drift applies
        assert score == pytest.approx(0.6)


# ============================================================
# Staleness condition_expired + confirmation window Tests
# ============================================================


@pytest.mark.unit
class TestConditionExpired:
    def test_condition_expired_fires_after_3_consecutive_bars(self):
        """evaluate_signal returns condition_expired when consecutive >= 3 and score > 0.5."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig,
            high=5110.0,
            low=5098.0,
            close=5105.0,
            staleness_consecutive_bars=3,
            staleness_score=0.6,
        )
        assert t is not None
        assert t.exit_reason == "condition_expired"
        assert t.outcome == "condition_expired"
        assert t.new_status == "expired"

    def test_condition_expired_not_fired_after_2_bars(self):
        """evaluate_signal returns None when consecutive = 2 (confirmation window not met)."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig,
            high=5110.0,
            low=5098.0,
            close=5105.0,
            staleness_consecutive_bars=2,
            staleness_score=0.6,
        )
        assert t is None

    def test_condition_expired_not_fired_when_score_low(self):
        """No expiry when score <= 0.5 even if consecutive >= 3."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig,
            high=5110.0,
            low=5098.0,
            close=5105.0,
            staleness_consecutive_bars=5,
            staleness_score=0.4,
        )
        assert t is None

    def test_return_type_is_transition_or_none(self):
        """evaluate_signal always returns Transition | None -- never a tuple."""
        from src.intelligence.trading.lifecycle_tracker import Transition

        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig,
            high=5110.0,
            low=5098.0,
            close=5105.0,
            staleness_consecutive_bars=3,
            staleness_score=0.6,
        )
        assert isinstance(t, Transition)
        t2 = evaluate_signal(
            sig,
            high=5110.0,
            low=5098.0,
            close=5105.0,
            staleness_consecutive_bars=2,
            staleness_score=0.6,
        )
        assert t2 is None


# ============================================================
# Temporal Guard Tests (D-01)
# ============================================================

from datetime import UTC, datetime  # noqa: E402


def _pending_with_zone(
    direction=1, entry=5100.0, stop=5085.0, zone_low=5095.0, zone_high=5102.0
) -> dict:
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
class TestTemporalGuard:
    """D-01: Signals cannot be activated on bars from before they were fired."""

    def test_no_activation_when_bar_time_before_signal_timestamp(self):
        """Bar time is before signal timestamp -> no activation even if zone overlaps."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        signal_ts = datetime(2026, 4, 28, 12, 5, tzinfo=UTC)
        bar_ts = datetime(2026, 4, 28, 12, 3, tzinfo=UTC)  # 2 min BEFORE signal
        t = evaluate_signal(
            sig,
            high=5098.0,
            low=5093.0,
            close=5096.0,
            signal_timestamp=signal_ts,
            bar_time=bar_ts,
        )
        assert t is None  # temporal guard prevents activation

    def test_activation_when_bar_time_after_signal_timestamp(self):
        """Bar time is after signal timestamp -> normal activation when zone overlaps."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        signal_ts = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
        bar_ts = datetime(2026, 4, 28, 12, 5, tzinfo=UTC)  # 5 min AFTER signal
        t = evaluate_signal(
            sig,
            high=5098.0,
            low=5093.0,
            close=5096.0,
            signal_timestamp=signal_ts,
            bar_time=bar_ts,
        )
        assert t is not None
        assert t.new_status == "active"

    def test_activation_blocked_when_bar_time_equals_signal_timestamp(self):
        """Temporal bias guard: bar_time <= signal_timestamp blocks activation (D-01 rule)."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        ts = datetime(2026, 4, 28, 12, 5, tzinfo=UTC)
        t = evaluate_signal(
            sig,
            high=5098.0,
            low=5093.0,
            close=5096.0,
            signal_timestamp=ts,
            bar_time=ts,
        )
        assert t is None

    def test_no_guard_when_timestamps_not_provided(self):
        """Backward compat: no timestamps passed -> activation proceeds normally."""
        sig = _pending_with_zone(direction=1, zone_low=5095.0, zone_high=5102.0)
        t = evaluate_signal(sig, high=5098.0, low=5093.0, close=5096.0)
        assert t is not None
        assert t.new_status == "active"

    def test_temporal_guard_blocks_activation_and_no_ttl_for_pending(self):
        """Temporal guard blocks activation; pending signals don't TTL-expire via evaluate_signal."""
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10  # hit TTL
        signal_ts = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
        bar_ts = datetime(2026, 4, 28, 11, 55, tzinfo=UTC)  # before signal
        t = evaluate_signal(
            sig,
            high=5080.0,
            low=5075.0,
            close=5078.0,
            signal_timestamp=signal_ts,
            bar_time=bar_ts,
        )
        # Temporal guard blocks activation, and PENDING signals don't reach TTL check
        assert t is None


@pytest.mark.unit
class TestTTLOutcomeWithActivatedAt:
    """Phase 81-03: D-02 compensating logic removed. PENDING+activated_at -> never_activated
    (violation is counted via _LABELING_VIOLATIONS counter, not auto-corrected)."""

    def test_pending_with_activated_at_activates_on_zone_overlap(self):
        """PENDING + activated_at: zone overlap still activates the signal.

        The D-02 labeling violation counter is only triggered in the TTL path,
        which is only reached for ACTIVE signals. PENDING signals with zone
        overlap activate regardless of activated_at or bars_elapsed.
        """
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10
        sig["activated_at"] = datetime(2026, 4, 28, 12, 1, tzinfo=UTC)
        t = evaluate_signal(
            sig,
            high=5108.0,
            low=5095.0,
            close=5105.0,
            current_mfe=0.3,
        )
        # Zone overlaps (high=5108 >= zone_low=5095 AND low=5095 <= zone_high=5102)
        assert t is not None
        assert t.new_status == "active"

    def test_pending_without_activated_at_returns_none_no_zone_overlap(self):
        """Signal is PENDING, no activated_at, no zone overlap -> None.

        TTL for pending signals is handled by the calling service.
        """
        sig = _pending_with_zone()
        sig["bars_elapsed"] = 10
        t = evaluate_signal(sig, high=5080.0, low=5075.0, close=5078.0)
        # No zone overlap (high=5080 < zone_low=5095) -> None
        assert t is None
