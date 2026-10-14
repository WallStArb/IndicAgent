"""session_complete_at: whether a 1d bar's NYSE session has closed at a given instant (D-191-J)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.intelligence.bars.sessions import session_complete_at


def test_open_session_is_not_complete():
    # AAPL 2026-09-30 example: answered 18:01 UTC, the close is 20:00 UTC (16:00 EDT)
    assert not session_complete_at(date(2026, 9, 30), datetime(2026, 9, 30, 18, 1, tzinfo=UTC))


def test_closed_session_is_complete_at_and_after_the_close():
    assert session_complete_at(date(2026, 9, 30), datetime(2026, 9, 30, 20, 0, tzinfo=UTC))
    assert session_complete_at(date(2026, 9, 30), datetime(2026, 10, 1, 1, 0, tzinfo=UTC))


def test_early_close_day_uses_the_early_close():
    # 2025-11-28 closes 13:00 ET = 18:00 UTC
    assert not session_complete_at(date(2025, 11, 28), datetime(2025, 11, 28, 17, 59, tzinfo=UTC))
    assert session_complete_at(date(2025, 11, 28), datetime(2025, 11, 28, 18, 0, tzinfo=UTC))


def test_future_session_is_not_complete():
    assert not session_complete_at(date(2026, 10, 2), datetime(2026, 10, 1, 21, 0, tzinfo=UTC))


def test_date_without_a_session_is_complete():
    # a calendar gap never withholds a bar that a vendor served for a past date
    assert session_complete_at(date(2026, 9, 26), datetime(2026, 9, 28, 12, 0, tzinfo=UTC))
