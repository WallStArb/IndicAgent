from datetime import UTC, datetime

import pytest

from src.providers.tradier import TradierError, parse_daily_history, tradier_symbol


def _day(date: str, close: float = 10.0, **overrides):
    row = {"date": date, "open": 9.0, "high": 11.0, "low": 8.5, "close": close, "volume": 100}
    return {**row, **overrides}


def test_parses_in_date_order_with_utc_midnight_keys():
    bars = parse_daily_history({"history": {"day": [_day("2026-01-05"), _day("2026-01-02")]}})
    assert [b.timestamp for b in bars] == [
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    ]


def test_single_bar_object_and_empty_history():
    assert len(parse_daily_history({"history": {"day": _day("2026-01-02")}})) == 1
    assert parse_daily_history({"history": None}) == []
    assert parse_daily_history({}) == []


def test_null_price_drops_the_day_and_never_fills():
    bars = parse_daily_history(
        {"history": {"day": [_day("2026-01-02", open=None), _day("2026-01-05")]}}
    )
    assert [b.timestamp.day for b in bars] == [5]


@pytest.mark.parametrize("bad", [0, -1.0, float("inf")])
def test_non_positive_or_non_finite_price_raises(bad):
    with pytest.raises(TradierError):
        parse_daily_history({"history": {"day": [_day("2026-01-02", close=bad)]}})


def test_duplicate_day_raises():
    with pytest.raises(TradierError):
        parse_daily_history({"history": {"day": [_day("2026-01-02"), _day("2026-01-02")]}})


def test_share_class_symbol_mapping():
    assert tradier_symbol("BRK.B") == "BRK/B"
