"""The alpaca nightly ends a sip window before the recent-SIP horizon (migration 513)."""

from datetime import UTC, datetime, timedelta

from scripts.ops.bars.ops_bar_nightly import request_end

NOW = datetime(2026, 10, 26, 14, 21, tzinfo=UTC)


def test_a_sip_window_ends_the_lag_before_now():
    assert request_end(NOW, "sip", 20) == NOW - timedelta(minutes=20)


def test_other_feeds_and_vendors_end_at_now():
    assert request_end(NOW, "iex", 20) == NOW
    assert request_end(NOW, None, 20) == NOW


def test_an_empty_answer_is_an_empty_typed_frame():
    """PSKY, WBD and QRVO (no longer served) crashed the 2026-10-26 catch-up on `.dt`: an
    empty answer must load zero rows, not raise."""
    import pandas as pd

    from scripts.ops.bars.ops_bar_nightly import _bars_frame

    frame = _bars_frame([])
    assert frame.empty and pd.api.types.is_datetime64_any_dtype(frame["t"])
    assert len(frame["t"].dt.to_pydatetime()) == 0


def test_timeframes_default_to_both_and_accept_one():
    """The 1d-only Alpaca history backfill (2026-10-27) asks one timeframe; the nightly asks both."""
    import pytest

    from scripts.ops.bars.ops_bar_nightly import parse_timeframes

    assert parse_timeframes(None) == ("5m", "1d")
    assert parse_timeframes("1d") == ("1d",)
    assert parse_timeframes("1d,5m") == ("5m", "1d")
    with pytest.raises(ValueError):
        parse_timeframes("1h")
