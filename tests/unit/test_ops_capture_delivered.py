"""The capture-delivered guard (todo 675): when the last completed session's bars count as in."""

from datetime import UTC, date, datetime

from scripts.ops.ops_capture_delivered import undelivered_session

# 2026-11-24 (Tue) and 2026-11-25 (Wed) are NYSE sessions; Wed closes 21:00Z.
AFTER_CLOSE = datetime(2026, 11, 25, 23, 54, tzinfo=UTC)
BEFORE_CLOSE = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)


def test_the_last_completed_session_with_no_bars_is_undelivered():
    assert undelivered_session(AFTER_CLOSE, {date(2026, 11, 24): 12000}) == date(2026, 11, 25)


def test_a_partial_capture_is_undelivered_and_a_full_one_is_delivered():
    partial = {date(2026, 11, 24): 12000, date(2026, 11, 25): 5000}
    full = {date(2026, 11, 24): 12000, date(2026, 11, 25): 11990}
    assert undelivered_session(AFTER_CLOSE, partial) == date(2026, 11, 25)
    assert undelivered_session(AFTER_CLOSE, full) is None


def test_before_the_close_the_last_completed_session_is_the_day_before():
    assert undelivered_session(BEFORE_CLOSE, {date(2026, 11, 24): 12000}) is None


def test_thanksgiving_week_compares_with_the_session_before_the_holiday():
    # 2026-11-26 is a market holiday; 2026-11-27 (Fri) is an early close at 18:00Z.
    after = datetime(2026, 11, 27, 19, 0, tzinfo=UTC)
    assert undelivered_session(after, {date(2026, 11, 25): 12000}) == date(2026, 11, 27)
    got = {date(2026, 11, 25): 12000, date(2026, 11, 27): 12000}
    assert undelivered_session(after, got) is None


def test_the_delivered_share_boundary_is_inclusive():
    exactly = {date(2026, 11, 24): 10000, date(2026, 11, 25): 9000}
    one_short = {date(2026, 11, 24): 10000, date(2026, 11, 25): 8999}
    assert undelivered_session(AFTER_CLOSE, exactly) is None
    assert undelivered_session(AFTER_CLOSE, one_short) == date(2026, 11, 25)
