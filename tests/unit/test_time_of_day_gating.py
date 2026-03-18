"""Unit tests for RollMonitor time-of-day gating.

Tests _apply_tod_adjustment() for all Eastern Time session windows:
- Pre-open (09:00–11:00 ET): threshold * 1.3
- Close (15:00 ET / hour==15): threshold * 0.9
- Post-close (16:00–18:00 ET): None (skip detection entirely)
- Standard RTH (12:00 ET): threshold unchanged
- TOD gating disabled (roll_time_of_day_gated=False): always unchanged
- Weekend timestamps

Also verifies that check_roll() respects _apply_tod_adjustment() returning None
by not incrementing confirmation count when post-close.

Phase 38 Plan 02 — TDD
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(*, tod_gated: bool = True) -> MagicMock:
    s = MagicMock()
    s.roll_monitor_enabled = True
    s.ib_host = "192.168.1.158"
    s.roll_monitor_window_size = 100
    s.roll_monitor_threshold_default = 1.2
    s.roll_confirmation_bars = 3
    s.roll_monitor_cooldown_min = 30
    s.roll_monitor_postroll_bars = 10
    s.roll_time_of_day_gated = tod_gated
    s.env_name = "dev"
    return s


def _make_roll_monitor(tod_gated: bool = True):
    from services.tws_daemon import RollMonitor  # noqa: PLC0415
    return RollMonitor(_make_settings(tod_gated=tod_gated))


# ---------------------------------------------------------------------------
# UTC → ET conversion reference:
#   2026-06-12 is a Friday (summer time, EDT = UTC-4)
#   09:00 ET = 13:00 UTC
#   10:00 ET = 14:00 UTC
#   12:00 ET = 16:00 UTC
#   15:00 ET = 19:00 UTC
#   17:00 ET = 21:00 UTC
# ---------------------------------------------------------------------------

BASE_THRESHOLD = 1.2


class TestPreOpenThreshold:
    """9:00–10:59 ET → threshold * 1.3"""

    def test_pre_open_threshold_multiplied_at_10am(self):
        rm = _make_roll_monitor()
        # 10:00 ET = 14:00 UTC on 2026-06-12
        utc_now = datetime(2026, 6, 12, 14, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD * 1.3)

    def test_pre_open_threshold_multiplied_at_9am(self):
        rm = _make_roll_monitor()
        # 9:00 ET = 13:00 UTC
        utc_now = datetime(2026, 6, 12, 13, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD * 1.3)

    def test_pre_open_edge_at_10_59(self):
        """10:59 ET is still in pre-open window (hour==10)."""
        rm = _make_roll_monitor()
        # 10:59 ET = 14:59 UTC
        utc_now = datetime(2026, 6, 12, 14, 59, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD * 1.3)


class TestCloseThreshold:
    """15:00–15:59 ET → threshold * 0.9"""

    def test_close_threshold_multiplied(self):
        rm = _make_roll_monitor()
        # 15:00 ET = 19:00 UTC
        utc_now = datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD * 0.9)

    def test_close_edge_at_15_59(self):
        """15:59 ET is still in close window (hour==15)."""
        rm = _make_roll_monitor()
        # 15:59 ET = 19:59 UTC
        utc_now = datetime(2026, 6, 12, 19, 59, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD * 0.9)


class TestPostCloseSkipped:
    """16:00–17:59 ET → None (skip detection)"""

    def test_post_close_skipped_at_17(self):
        rm = _make_roll_monitor()
        # 17:00 ET = 21:00 UTC
        utc_now = datetime(2026, 6, 12, 21, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result is None

    def test_post_close_skipped_at_16(self):
        rm = _make_roll_monitor()
        # 16:00 ET = 20:00 UTC
        utc_now = datetime(2026, 6, 12, 20, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result is None

    def test_post_close_edge_at_17_59(self):
        """17:59 ET is still post-close (hour==17)."""
        rm = _make_roll_monitor()
        # 17:59 ET = 21:59 UTC
        utc_now = datetime(2026, 6, 12, 21, 59, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result is None


class TestStandardRthUnchanged:
    """12:00 ET (standard RTH midday) → threshold unchanged"""

    def test_standard_rth_unchanged(self):
        rm = _make_roll_monitor()
        # 12:00 ET = 16:00 UTC
        utc_now = datetime(2026, 6, 12, 16, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD)

    def test_early_morning_overnight_unchanged(self):
        """3:00 ET (overnight ETH) → threshold unchanged (not in any special window)."""
        rm = _make_roll_monitor()
        # 3:00 ET = 7:00 UTC
        utc_now = datetime(2026, 6, 12, 7, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD)


class TestTodGatingDisabled:
    """With roll_time_of_day_gated=False, threshold always returns unchanged."""

    def test_tod_gating_disabled_pre_open(self):
        rm = _make_roll_monitor(tod_gated=False)
        # Would normally be pre-open (10:00 ET)
        utc_now = datetime(2026, 6, 12, 14, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD)

    def test_tod_gating_disabled_close(self):
        rm = _make_roll_monitor(tod_gated=False)
        # Would normally be close (15:00 ET)
        utc_now = datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert result == pytest.approx(BASE_THRESHOLD)

    def test_tod_gating_disabled_post_close(self):
        rm = _make_roll_monitor(tod_gated=False)
        # Would normally return None (17:00 ET)
        utc_now = datetime(2026, 6, 12, 21, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        # With gating disabled, must NOT return None
        assert result is not None
        assert result == pytest.approx(BASE_THRESHOLD)


class TestWeekendHandling:
    """Weekend timestamps should not cause errors."""

    def test_saturday_no_error(self):
        """Saturday at noon — any output is acceptable, just no exception."""
        rm = _make_roll_monitor()
        # 2026-06-13 (Saturday) 12:00 ET = 16:00 UTC
        utc_now = datetime(2026, 6, 13, 16, 0, tzinfo=UTC)
        # Should not raise
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert isinstance(result, (float, type(None)))

    def test_sunday_no_error(self):
        """Sunday overnight — any output is acceptable, just no exception."""
        rm = _make_roll_monitor()
        # 2026-06-14 (Sunday) 2:00 ET = 6:00 UTC
        utc_now = datetime(2026, 6, 14, 6, 0, tzinfo=UTC)
        result = rm._apply_tod_adjustment(BASE_THRESHOLD, utc_now)
        assert isinstance(result, (float, type(None)))


class TestTodAdjustmentIntegratedWithCheckRoll:
    """Verify check_roll() respects TOD adjustment returning None."""

    def _make_window_with_spike(self, rm, base="ES", baseline_bars=30):
        """Fill window with baseline then spike."""
        for _ in range(baseline_bars):
            rm.update_volume(base, 1000.0, 100.0)
        for _ in range(5):
            rm.update_volume(base, 1000.0, 50000.0)

    def test_post_close_detection_skipped_entirely(self):
        """Post-close window (17:00 ET): check_roll returns False, no confirmation increment."""
        rm = _make_roll_monitor(tod_gated=True)
        self._make_window_with_spike(rm)
        # 17:00 ET = 21:00 UTC — post-close
        utc_now = datetime(2026, 6, 12, 21, 0, tzinfo=UTC)
        result = rm.check_roll("ES", utc_now)
        assert result is False
        assert rm._confirmation_count["ES"] == 0

    def test_standard_rth_detection_proceeds(self):
        """Standard RTH (12:00 ET): check_roll processes the window (no post-close suppression).

        We verify that check_roll() does NOT suppress via TOD gating at 12:00 ET by
        confirming that a threshold/z-score candidate correctly increments the confirmation
        counter when given a fresh window with strong spike signal.
        """
        rm = _make_roll_monitor(tod_gated=True)
        # 12:00 ET = 16:00 UTC
        utc_now = datetime(2026, 6, 12, 16, 0, tzinfo=UTC)

        # Build a strong baseline with very low next_vol, then spike to create high z-score
        for _ in range(50):
            rm.update_volume("ES", 1000.0, 50.0)   # baseline: next_vol ~50, std low

        # Drive 3 consecutive spike bars to confirm roll
        confirmed = False
        for _ in range(6):
            rm.update_volume("ES", 1000.0, 100000.0)  # extreme spike
            if rm.check_roll("ES", utc_now):
                confirmed = True
                break

        # TOD gating must not suppress standard RTH — roll should confirm or counter advance
        assert confirmed or rm._confirmation_count["ES"] > 0, (
            "Standard RTH (12:00 ET) should not suppress roll detection via TOD gating"
        )
