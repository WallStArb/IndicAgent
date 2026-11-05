"""MarketCalendar.session_bounds: each session's own open and close (186-32)."""

from datetime import date

import pandas as pd
import pytest

from src.core.market_calendar import get_market_calendar


def test_regular_session_is_six_and_a_half_hours():
    open_ts, close_ts = get_market_calendar().session_bounds("NYSE", date(2024, 12, 2))
    assert open_ts == pd.Timestamp("2024-12-02 14:30", tz="UTC")
    assert close_ts - open_ts == pd.Timedelta(hours=6, minutes=30)


def test_early_close_shortens_the_session():
    # The day after Thanksgiving 2024 closes at 13:00 New York.
    open_ts, close_ts = get_market_calendar().session_bounds("NYSE", date(2024, 11, 29))
    assert close_ts == pd.Timestamp("2024-11-29 18:00", tz="UTC")
    assert close_ts - open_ts == pd.Timedelta(hours=3, minutes=30)


@pytest.mark.parametrize(
    ("exchange", "day"),
    [("NYSE", date(2024, 12, 1)), ("NYSE", date(1999, 12, 31)), ("SMART", date(2024, 12, 2))],
)
def test_non_session_date_or_unknown_exchange_raises(exchange, day):
    with pytest.raises(KeyError):
        get_market_calendar().session_bounds(exchange, day)
