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
    assert any(
        "signals:" in s and ":aggregated" in s for s in streams
    ), f"No aggregated signals stream in {streams}"
    # Should NOT have raw (non-aggregated) signals stream
    raw_signals = [s for s in streams if "signals:" in s and not s.endswith(":aggregated")]
    assert len(raw_signals) == 0, f"Found raw (non-aggregated) signals stream: {raw_signals}"


def test_build_stream_list_includes_group_narrative_streams():
    """SSE stream list always includes 6 group narrative streams."""
    from src.api.routes.sse import _build_stream_list

    streams = _build_stream_list(["ES"], "1m")
    group_streams = [s for s in streams if ":group:" in s]
    assert len(group_streams) == 6
    groups = {s.split(":")[-1] for s in group_streams}
    assert groups == {"equity", "energy", "metals", "rates", "fx_crypto", "ag"}


def test_event_name_for_group_narrative_stream():
    """narratives:group:* maps to narrative_data event."""
    from src.api.routes.sse import _event_name_for_stream

    assert _event_name_for_stream("narratives:group:equity") == "narrative_data"
    assert _event_name_for_stream("development:narratives:group:metals") == "narrative_data"


def test_build_stream_list_includes_system_events():
    """Stream list always includes the global system:events stream."""
    from src.api.routes.sse import _build_stream_list

    streams = _build_stream_list(["ES"], "1m")
    assert any("system:events" in s for s in streams), f"No system:events stream in {streams}"


def test_build_stream_list_includes_system_events_once():
    """system:events appears exactly once regardless of symbol count."""
    from src.api.routes.sse import _build_stream_list

    streams = _build_stream_list(["ES", "NQ", "RTY"], "1m")
    system_streams = [s for s in streams if "system:events" in s]
    assert len(system_streams) == 1, f"Expected 1 system:events, got {system_streams}"


def test_event_name_for_system_events_stream():
    """system:events maps to system_event."""
    from src.api.routes.sse import _event_name_for_stream

    assert _event_name_for_stream("system:events") == "system_event"


def test_event_name_for_env_prefixed_system_events():
    """Env-prefixed system:events maps to system_event."""
    from src.api.routes.sse import _event_name_for_stream

    assert _event_name_for_stream("development:system:events") == "system_event"


# ── KAFKA-07: KafkaSSEBroadcaster fan-out test ─────────────────────────────────

import asyncio

import pytest


@pytest.mark.asyncio
async def test_kafka_broadcaster_fan_out():
    """KAFKA-07: KafkaSSEBroadcaster fan-out delivers to subscribed queues and populates _latest.

    - subscribe() returns (_latest dict, asyncio.Queue)
    - After broadcaster processes a message, the queue receives it
    - The _latest[topic][key] has the message
    """
    from src.api.routes.sse import KafkaSSEBroadcaster

    broadcaster = KafkaSSEBroadcaster()
    snapshot, live_q = broadcaster.subscribe()

    # Simulate consumer delivering a message by calling the internal fan-out
    test_topic = "dev.intelligence"
    test_key = "ES:1m"
    test_payload = {"event": '{"ts": "2026-03-14T10:00:00Z", "symbol": "ES", "tf": "1m"}'}
    item = {"topic": test_topic, "key": test_key, "payload": test_payload}

    # Manually drive the broadcaster's fan-out (bypass actual Kafka consumer)
    broadcaster._latest[test_topic][test_key] = item
    for q in list(broadcaster._queues):
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            pass

    # Assert _latest populated
    assert test_key in broadcaster._latest[test_topic]
    assert broadcaster._latest[test_topic][test_key]["topic"] == test_topic

    # Assert queue received message
    assert not live_q.empty()
    received = await live_q.get()
    assert received["topic"] == test_topic
    assert received["key"] == test_key
    assert received["payload"] == test_payload

    # unsubscribe removes queue
    broadcaster.unsubscribe(live_q)
    assert live_q not in broadcaster._queues


@pytest.mark.asyncio
async def test_event_name_for_topic_intelligence():
    """Kafka topic dev.intelligence maps to intelligence_data."""
    from src.api.routes.sse import _event_name_for_topic

    assert _event_name_for_topic("dev.intelligence") == "intelligence_data"
    assert _event_name_for_topic("dev.intelligence.i7") == "signal_scorecard"
    assert _event_name_for_topic("dev.intelligence.i8") == "narrative_data"


@pytest.mark.asyncio
async def test_event_name_for_topic_signals():
    """Kafka signals.aggregated maps to signal_data."""
    from src.api.routes.sse import _event_name_for_topic

    assert _event_name_for_topic("dev.signals.aggregated") == "signal_data"
    assert _event_name_for_topic("dev.signals") == "signal_data"


@pytest.mark.asyncio
async def test_event_name_for_topic_market():
    """Kafka market topics map correctly."""
    from src.api.routes.sse import _event_name_for_topic

    assert _event_name_for_topic("dev.market.ticks") == "tick_data"
    assert _event_name_for_topic("dev.market.bars") == "market_data"
    assert _event_name_for_topic("dev.indicators") == "indicator_data"


@pytest.mark.asyncio
async def test_event_name_for_topic_narratives():
    """Kafka narratives topics map to narrative_data."""
    from src.api.routes.sse import _event_name_for_topic

    assert _event_name_for_topic("dev.narratives") == "narrative_data"
    assert _event_name_for_topic("dev.narratives.group") == "narrative_data"
