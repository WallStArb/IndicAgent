"""Tests for aggregated signal stream key."""

from src.core.stream_keys import signals_aggregated


def test_signals_aggregated_with_prefix():
    assert signals_aggregated("dev:", "ES", "5m") == "dev:signals:ES:5m:aggregated"


def test_signals_aggregated_no_prefix():
    assert signals_aggregated("", "NQ", "1h") == "signals:NQ:1h:aggregated"

# test_aggregated_maxlen removed — get_stream_maxlen removed in Phase 30 (DragonflyDB retired)
