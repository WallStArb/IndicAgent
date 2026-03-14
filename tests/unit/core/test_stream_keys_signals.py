"""Tests for signal stream key helpers."""
from src.core.stream_keys import signals


def test_signals_key_with_prefix():
    assert signals("dev:", "ES", "5m") == "dev:signals:ES:5m"


def test_signals_key_no_prefix():
    assert signals("", "NQ", "1h") == "signals:NQ:1h"

# test_signals_pattern removed — signals_pattern removed in Phase 30 (DragonflyDB retired)
# test_signals_maxlen removed — get_stream_maxlen removed in Phase 30 (DragonflyDB retired)
