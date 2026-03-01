"""
Unit tests for SSE intelligence_data payload format (API-03).

Verifies:
1. _event_name_for_stream maps intelligence: streams to "intelligence_data"
2. Payload structure: {"stream": ..., "id": ..., "payload": {"event": "<IntelligenceEvent JSON>"}}
3. Env-prefixed stream names (development:intelligence:ESH6:1m) also route correctly
"""

import json
from datetime import UTC, datetime

from src.api.routes.sse import _event_name_for_stream


def _make_minimal_event():
    """Build a minimal but valid IntelligenceEvent for fixture use."""
    from src.intelligence.schemas import (
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )

    return IntelligenceEvent(
        ts=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="1m",
        bar=OHLCVBar(o=5900.0, h=5910.0, low=5895.0, c=5905.0, v=1200),
        i1=I1Indicators(rsi_14=62.5, atr_14=8.3),
        i3=I3Structure(trend_direction=1.0),
        i4=I4Context(vol_regime=0.5, garch_sigma=0.0023),
        i5=I5Patterns(squeeze_active=0.0),
        smc=SMCContext(bos_detected=False),
        i6=I6Confluence(ctf_score=0.75),
    )


class TestEventNameMapping:
    """Test _event_name_for_stream routes stream names to correct SSE event names."""

    def test_intelligence_stream_maps_to_intelligence_data(self):
        """Raw intelligence: stream name maps to intelligence_data."""
        assert _event_name_for_stream("intelligence:ESH6:1m") == "intelligence_data"

    def test_prefixed_intelligence_stream_maps_to_intelligence_data(self):
        """Env-prefixed intelligence stream maps to intelligence_data."""
        assert _event_name_for_stream("development:intelligence:ESH6:1m") == "intelligence_data"

    def test_indicators_stream_maps_to_indicator_data(self):
        assert _event_name_for_stream("indicators:ESH6:1m") == "indicator_data"

    def test_signals_stream_maps_to_signal_data(self):
        assert _event_name_for_stream("signals:ESH6:1m:aggregated") == "signal_data"

    def test_market_stream_maps_to_market_data(self):
        assert _event_name_for_stream("market:ESH6:1m") == "market_data"

    def test_narratives_stream_maps_to_narrative_data(self):
        assert _event_name_for_stream("narratives:ESH6:1m") == "narrative_data"

    def test_unknown_stream_maps_to_message(self):
        assert _event_name_for_stream("unknown:stream") == "message"


class TestSSEPayloadFormat:
    """
    Test the SSE payload format for intelligence_data events.

    The SSE route passes raw Redis stream fields as payload.
    For intelligence: streams, market_analysis_service writes:
      redis.xadd(stream_key, {"event": event.model_dump_json()})
    So the SSE payload is: {"event": "<IntelligenceEvent JSON string>"}
    The dashboard does: JSON.parse(payload.event) to get the typed object.
    """

    def test_intelligence_event_serializes_to_json_string(self):
        """IntelligenceEvent.model_dump_json() produces a valid JSON string."""
        event = _make_minimal_event()
        json_str = event.model_dump_json()
        # Must be a string
        assert isinstance(json_str, str)
        # Must be valid JSON
        parsed = json.loads(json_str)
        assert parsed["symbol"] == "ESH6"
        assert parsed["tf"] == "1m"

    def test_sse_payload_structure_contains_event_field(self):
        """
        The SSE payload dict structure: {"event": "<IntelligenceEvent JSON>"}.
        When the dashboard receives this, it calls JSON.parse(payload.event).
        Verify the structure is json.dumps-serializable with event as a string.
        """
        event = _make_minimal_event()
        # Simulate what market_analysis_service writes to Redis
        redis_fields = {"event": event.model_dump_json()}
        # Simulate what SSE route emits: json.dumps({"stream": ..., "id": ..., "payload": fields})
        sse_data = json.dumps(
            {"stream": "intelligence:ESH6:1m", "id": "12345-0", "payload": redis_fields}
        )
        # Must be valid JSON
        parsed = json.loads(sse_data)
        assert "payload" in parsed
        assert "event" in parsed["payload"]
        # payload.event must be a JSON string (not a dict) — client calls JSON.parse on it
        assert isinstance(parsed["payload"]["event"], str)
        # And that JSON string must parse to a valid IntelligenceEvent-shaped dict
        inner = json.loads(parsed["payload"]["event"])
        assert inner["symbol"] == "ESH6"
        assert inner["tf"] == "1m"
        assert "ts" in inner
