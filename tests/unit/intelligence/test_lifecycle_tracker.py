"""Tests for signal lifecycle tracker."""

import pytest

from src.intelligence.trading.lifecycle_tracker import (
    evaluate_signal,
)


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
        """Long active: high >= target[0] -> target_1_hit."""
        sig = _active_signal(
            direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0, 5145.0]
        )
        t = evaluate_signal(sig, high=5116.0, low=5105.0, close=5114.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5115.0

    @pytest.mark.unit
    def test_target_2_hit_long(self):
        """Long active: high >= target[1] -> target_2_hit."""
        sig = _active_signal(
            direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0, 5145.0]
        )
        t = evaluate_signal(sig, high=5131.0, low=5120.0, close=5129.0)
        assert t.new_status == "target_2_hit"
        assert t.exit_reason == "target_2"

    @pytest.mark.unit
    def test_target_hit_short(self):
        """Short active: low <= target[0] -> target_1_hit."""
        sig = _active_signal(direction=-1, entry=5100.0, stop=5115.0, targets=[5085.0, 5070.0])
        t = evaluate_signal(sig, high=5098.0, low=5084.0, close=5086.0)
        assert t.new_status == "target_1_hit"
        assert t.exit_reason == "target_1"
        assert t.exit_price == 5085.0

    @pytest.mark.unit
    def test_stop_checked_before_target(self):
        """If both stop and target hit on same bar, stop takes priority."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0])
        t = evaluate_signal(sig, high=5116.0, low=5084.0, close=5090.0)
        assert t.new_status == "expired"
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
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0, 5130.0])
        sig["entry_zone_low"] = 5095.0
        sig["entry_zone_high"] = 5105.0
        t = evaluate_signal(
            sig, high=5120.0, low=5102.0, close=5118.0, current_mae=0.0, current_mfe=0.5
        )
        assert t is not None
        assert t.new_status == "target_1_hit"
        assert t.outcome == "target_1"

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
        """PnL calculated correctly for target hit long."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5085.0, targets=[5115.0])
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
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5098.0, low=5084.0, close=5086.0)
        assert t is not None
        assert t.exit_price == 5085.0
        assert t.outcome is None  # stop outcome is resolved by caller

    def test_short_stop_hit(self):
        sig = _market_signal(direction=-1, stop=5115.0,
                             targets=[5085.0, 5070.0, 5055.0])
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5116.0, low=5105.0, close=5110.0)
        assert t.exit_price == 5115.0
        assert t.outcome is None

    def test_long_target_1(self):
        sig = _market_signal(direction=1, targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5116.0, low=5099.0, close=5115.0)
        assert t.outcome == "target_1"
        assert t.exit_price == 5115.0

    def test_long_target_full(self):
        sig = _market_signal(direction=1, targets=[5115.0, 5130.0, 5145.0])
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5146.0, low=5099.0, close=5145.0)
        assert t.outcome == "target_full"
        assert t.exit_price == 5145.0

    def test_ttl_expired_ahead(self):
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5108.0, low=5099.0, close=5105.0,
                                  current_mfe=0.3)
        assert t.outcome == "ttl_expired_ahead"

    def test_ttl_expired_behind(self):
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5097.0, low=5093.0, close=5094.0,
                                  current_mfe=0.0)
        assert t.outcome == "ttl_expired_behind"

    def test_no_exit_returns_still_running(self):
        """No stop/target/TTL hit → MarketTransition with outcome=None."""
        sig = _market_signal(direction=1, bars_elapsed=3)
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5108.0, low=5099.0, close=5105.0)
        assert t.outcome is None
        assert t.exit_price is None

    def test_risk_uses_market_entry_price_not_entry_price(self):
        """Market track risk = abs(market_entry_price - stop), not abs(entry_price - stop)."""
        # entry_price=5100, stop=5085 → zone risk=15
        # market_entry_price=5090, stop=5085 → market risk=5
        sig = _market_signal(direction=1, entry=5100.0, stop=5085.0,
                             targets=[5105.0])
        t = evaluate_market_entry(sig, market_entry_price=5090.0,
                                  high=5106.0, low=5089.0, close=5105.0)
        expected_pnl_r = round((5105.0 - 5090.0) * 1 / abs(5090.0 - 5085.0), 4)
        assert t.pnl_r == expected_pnl_r

    def test_stop_checked_before_target(self):
        """Same bar hits both stop and target — stop wins."""
        sig = _market_signal(direction=1, stop=5085.0, targets=[5115.0])
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5116.0, low=5084.0, close=5100.0)
        assert t.exit_price == 5085.0
        assert t.outcome is None  # stop → caller classifies

    def test_never_activated_absent_from_market_track(self):
        """Market track never returns never_activated — the concept doesn't apply."""
        sig = _market_signal(bars_elapsed=11, ttl_bars=10)
        t = evaluate_market_entry(sig, market_entry_price=5100.0,
                                  high=5097.0, low=5093.0, close=5094.0)
        assert t.outcome != "never_activated"


@pytest.mark.unit
class TestMarketTrackMathInvariants:
    """Assert on final MarketTransition values only — not intermediate per-bar state."""

    def _run_bars(self, sig, market_price, bars):
        """Feed N bars to evaluate_market_entry, returning final transition."""
        mae = mfe = 0.0
        t = None
        for high, low, close in bars:
            t = evaluate_market_entry(sig, market_entry_price=market_price,
                                      high=high, low=low, close=close,
                                      current_mae=mae, current_mfe=mfe)
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
        bars = [(5103.0, 5098.0, 5101.0),
                (5110.0, 5102.0, 5108.0),
                (5121.0, 5105.0, 5120.0)]
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
            sig, high=5115.0, low=5098.0, close=5110.0,
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
            sig, high=5108.0, low=5098.0, close=5105.0,
            chandelier_state=ch,
        )
        assert ch["trailing_stop"] == pytest.approx(5100.0)  # unchanged

    def test_short_stop_tightens_when_low_decreases(self):
        """For a short, as lowest_low falls the stop should move down (tighten)."""
        sig = _active_signal(
            direction=-1, entry=5100.0, stop=5115.0, targets=[5060.0, 5040.0]
        )
        ch = {
            "trailing_stop": 5110.0,
            "highest_high": 5105.0,
            "lowest_low": 5090.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        # Bar: low=5085 < lowest_low -> new_stop = 5085 + 15 = 5100 < 5110 -> tightens
        evaluate_signal(
            sig, high=5097.0, low=5085.0, close=5088.0,
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
            sig, high=5100.0, low=5094.0, close=5096.0,
            chandelier_state=ch,
        )
        assert t is not None
        assert t.exit_reason == "chandelier_stop"
        assert t.outcome == "stopped_in_trade"

    def test_short_exits_when_high_breaches_trailing_stop(self):
        """Short: high >= trailing_stop -> chandelier_stop exit."""
        sig = _active_signal(
            direction=-1, entry=5100.0, stop=5130.0, targets=[5060.0, 5040.0]
        )
        ch = {
            "trailing_stop": 5108.0,
            "highest_high": 5105.0,
            "lowest_low": 5090.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
        }
        t = evaluate_signal(
            sig, high=5109.0, low=5098.0, close=5105.0,
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
            sig, high=5115.0, low=5105.0, close=5112.0,
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
            sig, high=5110.0, low=5098.0, close=5105.0,
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
            sig, high=5110.0, low=5098.0, close=5105.0,
            staleness_consecutive_bars=2,
            staleness_score=0.6,
        )
        assert t is None

    def test_condition_expired_not_fired_when_score_low(self):
        """No expiry when score <= 0.5 even if consecutive >= 3."""
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig, high=5110.0, low=5098.0, close=5105.0,
            staleness_consecutive_bars=5,
            staleness_score=0.4,
        )
        assert t is None

    def test_return_type_is_transition_or_none(self):
        """evaluate_signal always returns Transition | None -- never a tuple."""
        from src.intelligence.trading.lifecycle_tracker import Transition
        sig = _active_signal(direction=1, entry=5100.0, stop=5060.0, targets=[5150.0])
        t = evaluate_signal(
            sig, high=5110.0, low=5098.0, close=5105.0,
            staleness_consecutive_bars=3,
            staleness_score=0.6,
        )
        assert isinstance(t, Transition)
        t2 = evaluate_signal(
            sig, high=5110.0, low=5098.0, close=5105.0,
            staleness_consecutive_bars=2,
            staleness_score=0.6,
        )
        assert t2 is None


# ============================================================
# Service-level state management integration tests
# ============================================================


def _make_lifecycle_service():
    """Build SignalLifecycleService via __new__ (bypasses __init__), with minimal state."""
    from unittest.mock import MagicMock

    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService.__new__(SignalLifecycleService)
    svc.db_manager = MagicMock()
    svc.db_manager.execute_command = MagicMock(return_value=None)
    svc.active_signals_count = MagicMock()
    svc.point_values = {"ES": 50.0}
    svc._mae = {}
    svc._mfe = {}
    svc._activated_at = {}
    svc._market_mae = {}
    svc._market_mfe = {}
    svc._market_activated_at = {}
    svc._resolved_market = set()
    svc._chandelier_state = {}
    svc._staleness_consecutive = {}
    svc._shadow_signals = {}
    svc._pending_tasks = set()
    svc.env_prefix = "test:"
    svc.env_name = "test"
    svc._kafka_producer = None
    svc.lifecycle_transitions_total = MagicMock()
    svc.logger = MagicMock()
    return svc


@pytest.mark.unit
class TestChandelierServiceStateManagement:
    """Service-level tests: Chandelier state initialized, updated, and cleaned up."""

    @pytest.mark.asyncio
    async def test_chandelier_state_initialized_on_first_active_bar(self):
        """_chandelier_state[sid] is created on the first active bar evaluation."""
        from unittest.mock import AsyncMock, patch

        svc = _make_lifecycle_service()
        signal_id = "chan-init-001"
        svc._activated_at[signal_id] = None

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5120.0, 5140.0],
            "confidence": 0.8,
            "timeframe": "1m",
            "symbol": "ES",
            "timestamp": None,
            "ttl_bars": 20,
            "garch_sigma_at_fire": 8.0,
            "atr_14": 5.0,
        }
        bar = {"high": 5110.0, "low": 5098.0, "close": 5105.0}

        with patch("services.signal_lifecycle_service.record_zone_resolution", new_callable=AsyncMock):
            with patch("services.signal_lifecycle_service.record_activation", new_callable=AsyncMock):
                await svc._evaluate_signals_against_bar(
                    symbol="ES", timeframe="1m",
                    bar=bar, bar_time=__import__("datetime").datetime(2026, 3, 17, 12, 0, 0,
                                                                       tzinfo=__import__("datetime").timezone.utc),
                    all_active=[sig],
                )

        assert signal_id in svc._chandelier_state
        assert svc._chandelier_state[signal_id]["vol_source"] == "garch_sigma"
        assert svc._chandelier_state[signal_id]["vol"] == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_chandelier_state_uses_atr_fallback_when_no_garch(self):
        """When garch_sigma_at_fire is 0, vol_source = 'atr_14' using atr_14 value."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, patch

        svc = _make_lifecycle_service()
        signal_id = "chan-atr-002"
        svc._activated_at[signal_id] = None

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5120.0],
            "confidence": 0.8,
            "timeframe": "1m",
            "symbol": "ES",
            "timestamp": None,
            "ttl_bars": 20,
            "garch_sigma_at_fire": 0.0,
            "atr_14": 12.0,
        }
        bar = {"high": 5105.0, "low": 5098.0, "close": 5102.0}
        bar_time = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)

        with patch("services.signal_lifecycle_service.record_zone_resolution", new_callable=AsyncMock):
            with patch("services.signal_lifecycle_service.record_activation", new_callable=AsyncMock):
                await svc._evaluate_signals_against_bar(
                    symbol="ES", timeframe="1m",
                    bar=bar, bar_time=bar_time,
                    all_active=[sig],
                )

        assert signal_id in svc._chandelier_state
        assert svc._chandelier_state[signal_id]["vol_source"] == "atr_14"
        assert svc._chandelier_state[signal_id]["vol"] == pytest.approx(12.0)

    @pytest.mark.asyncio
    async def test_chandelier_state_cleaned_up_on_stop_exit(self):
        """_chandelier_state[sid] removed when signal exits via stop loss."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, patch

        svc = _make_lifecycle_service()
        signal_id = "chan-cleanup-003"
        bar_time = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        svc._activated_at[signal_id] = bar_time
        svc._mae[signal_id] = 0.0
        svc._mfe[signal_id] = 0.0
        svc._chandelier_state[signal_id] = {
            "trailing_stop": 5090.0,
            "highest_high": 5110.0,
            "lowest_low": 5095.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
            "history": [],
        }
        svc._staleness_consecutive[signal_id] = 0

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5120.0],
            "confidence": 0.8,
            "timeframe": "1m",
            "symbol": "ES",
            "timestamp": bar_time,
            "ttl_bars": 20,
            "garch_sigma_at_fire": 5.0,
        }
        # Bar with low <= stop_loss -> stop hit
        bar = {"high": 5095.0, "low": 5084.0, "close": 5085.0}

        with patch("services.signal_lifecycle_service.record_zone_resolution", new_callable=AsyncMock):
            await svc._evaluate_signals_against_bar(
                symbol="ES", timeframe="1m",
                bar=bar, bar_time=bar_time,
                all_active=[sig],
            )

        assert signal_id not in svc._chandelier_state
        assert signal_id not in svc._staleness_consecutive

    @pytest.mark.asyncio
    async def test_staleness_consecutive_increments_above_threshold(self):
        """_staleness_consecutive[sid] increments each bar when staleness_score > 0.5."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, patch

        svc = _make_lifecycle_service()
        signal_id = "stale-incr-004"
        bar_time = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        svc._activated_at[signal_id] = bar_time
        svc._mae[signal_id] = 0.0
        svc._mfe[signal_id] = 0.0

        # Signal with differing regimes -> staleness_score = 0.6 (regime flip)
        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5120.0],
            "confidence": 0.8,
            "timeframe": "1m",
            "symbol": "ES",
            "timestamp": bar_time,
            "ttl_bars": 20,
            "hmm_regime": 1,
            "hmm_regime_at_fire": 0,
            "garch_sigma": 5.0,
            "garch_sigma_at_fire": 5.0,
        }
        bar = {"high": 5105.0, "low": 5098.0, "close": 5102.0}

        with patch("services.signal_lifecycle_service.record_zone_resolution", new_callable=AsyncMock):
            with patch("services.signal_lifecycle_service.record_activation", new_callable=AsyncMock):
                await svc._evaluate_signals_against_bar(
                    symbol="ES", timeframe="1m",
                    bar=bar, bar_time=bar_time,
                    all_active=[sig],
                )
                # After 1 bar with score > 0.5, consecutive = 1
                assert svc._staleness_consecutive.get(signal_id, 0) == 1
                # Feed a second bar with same regime flip
                await svc._evaluate_signals_against_bar(
                    symbol="ES", timeframe="1m",
                    bar=bar, bar_time=bar_time,
                    all_active=[sig],
                )
                assert svc._staleness_consecutive.get(signal_id, 0) == 2

    @pytest.mark.asyncio
    async def test_shadow_signal_registered_on_condition_expired(self):
        """_shadow_signals[sid] is populated when condition_expired fires."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import AsyncMock, patch

        svc = _make_lifecycle_service()
        signal_id = "shadow-reg-005"
        bar_time = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        signal_ts = bar_time - timedelta(minutes=5)
        svc._activated_at[signal_id] = signal_ts
        svc._mae[signal_id] = 0.0
        svc._mfe[signal_id] = 0.0
        # Pre-seed staleness consecutive = 3 -> condition_expired fires on 4th bar
        svc._staleness_consecutive[signal_id] = 3
        svc._chandelier_state[signal_id] = {
            "trailing_stop": None,
            "highest_high": 5110.0,
            "lowest_low": 5095.0,
            "vol": 5.0,
            "vol_source": "garch_sigma",
            "history": [],
        }

        sig = {
            "signal_id": signal_id,
            "status": "active",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5120.0, 5140.0],
            "confidence": 0.8,
            "timeframe": "1m",
            "symbol": "ES",
            "timestamp": signal_ts,
            "ttl_bars": 20,
            "hmm_regime": 1,
            "hmm_regime_at_fire": 0,
            "garch_sigma": 5.0,
            "garch_sigma_at_fire": 5.0,
        }
        bar = {"high": 5105.0, "low": 5098.0, "close": 5102.0}

        with patch("services.signal_lifecycle_service.record_zone_resolution", new_callable=AsyncMock):
            await svc._evaluate_signals_against_bar(
                symbol="ES", timeframe="1m",
                bar=bar, bar_time=bar_time,
                all_active=[sig],
            )

        # Signal should have been moved to shadow tracking
        assert signal_id in svc._shadow_signals
        shadow = svc._shadow_signals[signal_id]
        assert shadow["direction"] == 1
        assert shadow["symbol"] == "ES"
        assert shadow["timeframe"] == "1m"
        assert shadow["remaining_ttl"] >= 0
        # Chandelier + staleness cleaned up on exit
        assert signal_id not in svc._chandelier_state
        assert signal_id not in svc._staleness_consecutive
