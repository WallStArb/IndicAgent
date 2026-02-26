"""Tests for SSE stream builder helper functions."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))



def test_event_name_for_narrative_stream():
    """narratives: prefix maps to narrative_data event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("narratives:ESH6:5m") == "narrative_data"


def test_event_name_for_aggregated_signal_stream():
    """signals:...:aggregated maps to signal_data event."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("signals:ESH6:5m:aggregated") == "signal_data"


def test_event_name_for_env_prefixed_narrative():
    """env-prefixed narratives stream maps correctly."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("dev:narratives:ESH6:5m") == "narrative_data"


def test_event_name_for_env_prefixed_aggregated_signal():
    """env-prefixed aggregated signal stream maps correctly."""
    from src.api.routes.sse import _event_name_for_stream
    assert _event_name_for_stream("dev:signals:NQH6:15m:aggregated") == "signal_data"


def test_build_stream_list_includes_narratives():
    """Stream list includes narratives stream for each symbol."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES"], "5m")
    assert any("narratives:" in s for s in streams), f"No narratives stream in {streams}"


def test_build_stream_list_uses_aggregated_not_raw():
    """Stream list uses signals:aggregated, not raw signals stream."""
    from src.api.routes.sse import _build_stream_list
    streams = _build_stream_list(["ES"], "5m")
    # Should have aggregated
    assert any("signals:" in s and ":aggregated" in s for s in streams), \
        f"No aggregated signals stream in {streams}"
    # Should NOT have raw (non-aggregated) signals stream
    raw_signals = [s for s in streams if "signals:" in s and not s.endswith(":aggregated")]
    assert len(raw_signals) == 0, f"Found raw (non-aggregated) signals stream: {raw_signals}"
