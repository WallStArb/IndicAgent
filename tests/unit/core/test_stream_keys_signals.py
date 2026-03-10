"""Tests for signal stream key helpers."""
from src.core.stream_keys import get_stream_maxlen, signals, signals_pattern


def test_signals_key_with_prefix():
    assert signals("dev:", "ES", "5m") == "dev:signals:ES:5m"


def test_signals_key_no_prefix():
    assert signals("", "NQ", "1h") == "signals:NQ:1h"


def test_signals_pattern():
    assert signals_pattern("dev:") == "dev:signals:*:*"


def test_signals_maxlen():
    assert get_stream_maxlen("1m", "signals") == 500
