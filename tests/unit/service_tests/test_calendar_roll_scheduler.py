"""Unit tests for CalendarRollScheduler — TDD for dual-detector roll design.

CalendarRollScheduler fires once per roll cycle at roll_end date (expiry - 3 days).
Keyed by (base_symbol, roll_end_date) to prevent re-firing within a cycle.
Publishes RollEvent with detection_method="calendar" when it fires.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scheduler():
    from services.roll_compute_agent import CalendarRollScheduler
    return CalendarRollScheduler()


def _utc_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test 1: Class exists
# ---------------------------------------------------------------------------


def test_calendar_roll_scheduler_class_exists():
    """CalendarRollScheduler must exist in roll_compute_agent module."""
    from services.roll_compute_agent import CalendarRollScheduler
    assert CalendarRollScheduler is not None


# ---------------------------------------------------------------------------
# Test 2: Does not fire before roll_end date
# ---------------------------------------------------------------------------


def test_does_not_fire_before_roll_end():
    """check_calendar_roll returns False when today is before roll_end date."""
    scheduler = _make_scheduler()

    # Use a known roll window: get_roll_window returns (roll_start, roll_end)
    # Simulate being one day before roll_end
    fake_roll_end = date(2026, 6, 16)   # arbitrary future date
    fake_roll_start = fake_roll_end - timedelta(days=11)
    before_roll_end = _utc_datetime(fake_roll_end - timedelta(days=1))

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        result = scheduler.check_calendar_roll("ES", before_roll_end)

    assert result is False


# ---------------------------------------------------------------------------
# Test 3: Fires on roll_end date
# ---------------------------------------------------------------------------


def test_fires_on_roll_end_date():
    """check_calendar_roll returns True when today == roll_end date."""
    scheduler = _make_scheduler()

    fake_roll_end = date(2026, 6, 16)
    fake_roll_start = fake_roll_end - timedelta(days=11)
    on_roll_end = _utc_datetime(fake_roll_end)

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        result = scheduler.check_calendar_roll("ES", on_roll_end)

    assert result is True


# ---------------------------------------------------------------------------
# Test 4: Fires after roll_end date (fallback — volume may have been late)
# ---------------------------------------------------------------------------


def test_fires_after_roll_end_date():
    """check_calendar_roll returns True when today > roll_end date and not yet fired."""
    scheduler = _make_scheduler()

    fake_roll_end = date(2026, 6, 16)
    fake_roll_start = fake_roll_end - timedelta(days=11)
    after_roll_end = _utc_datetime(fake_roll_end + timedelta(days=1))

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        result = scheduler.check_calendar_roll("ES", after_roll_end)

    assert result is True


# ---------------------------------------------------------------------------
# Test 5: Fires only once per cycle (idempotent)
# ---------------------------------------------------------------------------


def test_fires_only_once_per_cycle():
    """check_calendar_roll returns True on first call at roll_end, False on subsequent calls."""
    scheduler = _make_scheduler()

    fake_roll_end = date(2026, 6, 16)
    fake_roll_start = fake_roll_end - timedelta(days=11)
    on_roll_end = _utc_datetime(fake_roll_end)

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        first = scheduler.check_calendar_roll("ES", on_roll_end)
        second = scheduler.check_calendar_roll("ES", on_roll_end)
        third = scheduler.check_calendar_roll("ES", on_roll_end + timedelta(hours=2))

    assert first is True
    assert second is False
    assert third is False


# ---------------------------------------------------------------------------
# Test 6: Different symbols fire independently
# ---------------------------------------------------------------------------


def test_different_symbols_fire_independently():
    """ES and NQ fire independently — firing ES does not suppress NQ."""
    scheduler = _make_scheduler()

    fake_roll_end = date(2026, 6, 16)
    fake_roll_start = fake_roll_end - timedelta(days=11)
    on_roll_end = _utc_datetime(fake_roll_end)

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        es_fired = scheduler.check_calendar_roll("ES", on_roll_end)
        nq_fired = scheduler.check_calendar_roll("NQ", on_roll_end)

    assert es_fired is True
    assert nq_fired is True


# ---------------------------------------------------------------------------
# Test 7: Returns False when outside any roll window (get_roll_window returns None)
# ---------------------------------------------------------------------------


def test_returns_false_when_outside_roll_window():
    """check_calendar_roll returns False when get_roll_window returns None."""
    scheduler = _make_scheduler()
    now = datetime(2026, 4, 17, 14, 30, tzinfo=UTC)

    with patch("services.roll_compute_agent.get_roll_window", return_value=None):
        result = scheduler.check_calendar_roll("ES", now)

    assert result is False


# ---------------------------------------------------------------------------
# Test 8: Returns False for unknown base_symbol (ValueError from get_roll_window)
# ---------------------------------------------------------------------------


def test_returns_false_for_unknown_symbol():
    """check_calendar_roll returns False (not raises) for unknown base symbol."""
    scheduler = _make_scheduler()
    now = datetime(2026, 4, 17, 14, 30, tzinfo=UTC)

    with patch("services.roll_compute_agent.get_roll_window", side_effect=ValueError("unknown")):
        result = scheduler.check_calendar_roll("UNKNOWN", now)

    assert result is False


# ---------------------------------------------------------------------------
# Test 9: get_last_roll_end returns the roll_end date used for last fire
# ---------------------------------------------------------------------------


def test_get_last_fired_roll_end():
    """After firing, get_last_fired_roll_end returns the roll_end date for that symbol."""
    scheduler = _make_scheduler()

    fake_roll_end = date(2026, 6, 16)
    fake_roll_start = fake_roll_end - timedelta(days=11)
    on_roll_end = _utc_datetime(fake_roll_end)

    with patch("services.roll_compute_agent.get_roll_window", return_value=(fake_roll_start, fake_roll_end)):
        scheduler.check_calendar_roll("ES", on_roll_end)

    assert scheduler.get_last_fired_roll_end("ES") == fake_roll_end
    assert scheduler.get_last_fired_roll_end("NQ") is None
