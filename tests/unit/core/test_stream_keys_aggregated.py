"""Tests for aggregated signal stream key."""

from src.core.stream_keys import get_stream_maxlen, signals_aggregated


def test_signals_aggregated_with_prefix():
    assert signals_aggregated("dev:", "ES", "5m") == "dev:signals:ES:5m:aggregated"


def test_signals_aggregated_no_prefix():
    assert signals_aggregated("", "NQ", "1h") == "signals:NQ:1h:aggregated"


def test_aggregated_maxlen():
    assert get_stream_maxlen("1m", "signals_aggregated") == 200
