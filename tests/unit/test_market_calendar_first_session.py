"""The session calendar's first session bounds the 1d session_coverage era."""

from datetime import date

import pytest

from src.core.market_calendar import get_market_calendar


def test_first_nyse_session_is_the_first_trading_day_of_the_calendar():
    calendar = get_market_calendar()
    first = calendar.first_session("NYSE")
    assert first == date(2005, 1, 3)
    assert calendar.is_trading_day("NYSE", first)
    assert not calendar.is_trading_day("NYSE", date(2004, 12, 31))


def test_first_session_of_an_unknown_exchange_raises():
    with pytest.raises(KeyError):
        get_market_calendar().first_session("NOPE")
