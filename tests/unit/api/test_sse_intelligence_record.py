"""
Unit tests for SSE topic routing and payload shapes.

Verifies:
1. intelligence.i7 topic not in sse_topics() (retired)
2. intelligence.journal topic present in sse_topics() (current scorecard source)
3. BarIntelligenceRecord.ranked_signals serializes to the expected signal_scorecard payload shape
"""

import json
from datetime import UTC, datetime

from src.api.routes.sse import _event_name_for_topic, sse_topics
from src.core.stream_keys import (
    topic_intelligence_journal,
)


class TestBuildTopicList:
    """sse_topics() uses intelligence.record, not intelligence.i7."""

    def test_intelligence_record_in_topic_list(self):
        """intelligence.journal topic must appear in sse_topics().

        Phase 44.3 rewired SSE from intelligence.record to topic_intelligence_journal
        (topic string: intelligence.journal).
        """
        topics = sse_topics("")
        assert any(
            "intelligence.journal" in t for t in topics
        ), f"Expected a topic containing 'intelligence.journal' in topic list, got: {topics}"

    def test_intelligence_i7_not_in_topic_list(self):
        """intelligence.i7 topic must NOT appear in sse_topics() after rewire."""
        topics = sse_topics("")
        assert not any(
            "intelligence.i7" in t for t in topics
        ), f"Expected no topic containing 'intelligence.i7' in topic list, got: {topics}"


class TestBarIntelligenceRecordPayloadShape:
    """BarIntelligenceRecord produces a payload compatible with dashboard parsing."""

    def _make_ranked_signal(
        self,
        plugin: str = "trad_TrendFollowing",
        direction: int = 1,
        raw_confidence: float = 0.6,
        calibrated_confidence: float = 0.65,
        is_winner: bool = False,
    ):
        from src.intelligence.schemas import RankedSignal

        return RankedSignal(
            signal_id="test-uuid-1234",
            plugin=plugin,
            direction=direction,
            raw_confidence=raw_confidence,
            calibrated_confidence=calibrated_confidence,
            regime_eligible=True,
            quality_score=0.8,
            tod_multiplier=1.0,
            adjusted_rank=0.7,
            is_winner=is_winner,
        )

    def test_ranked_signal_has_is_winner_field(self):
        """RankedSignal model includes is_winner boolean field."""
        sig = self._make_ranked_signal(is_winner=True)
        assert sig.is_winner is True

    def test_ranked_signals_serialize_to_expected_array(self):
        """ranked_signals list serializes to JSON array with all required fields."""
        signals = [
            self._make_ranked_signal(plugin="trad_TrendFollowing", is_winner=True),
            self._make_ranked_signal(plugin="trad_MeanReversion", direction=-1),
        ]
        data = json.dumps([s.model_dump() for s in signals])
        parsed = json.loads(data)
        assert len(parsed) == 2
        assert parsed[0]["plugin"] == "trad_TrendFollowing"
        assert parsed[0]["is_winner"] is True
        assert parsed[1]["plugin"] == "trad_MeanReversion"
        assert parsed[1]["is_winner"] is False

    def test_signal_scorecard_payload_shape(self):
        """signal_scorecard payload shape matches what the dashboard expects.

        Dashboard parses: JSON.parse(String(payload.data || '[]'))
        So payload must have: {ts, symbol, tf, data: "<JSON array string>"}
        """
        signals = [self._make_ranked_signal()]
        now = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        payload = {
            "ts": now.isoformat(),
            "symbol": "ES",
            "tf": "1m",
            "data": json.dumps([s.model_dump() for s in signals]),
        }
        # data must be a JSON string (not a list) — dashboard calls JSON.parse on it
        assert isinstance(payload["data"], str)
        parsed_data = json.loads(payload["data"])
        assert len(parsed_data) == 1
        sig = parsed_data[0]
        assert sig["plugin"] == "trad_TrendFollowing"
        assert "is_winner" in sig
        assert "calibrated_confidence" in sig
        assert "adjusted_rank" in sig


class TestStreamKeysLiveTopics:
    """stream_keys topic builders for current active topics."""

    def test_topic_intelligence_journal_available(self):
        """topic_intelligence_journal must be importable and return correct topic string."""
        result = topic_intelligence_journal("")
        assert result == "intelligence.journal"


class TestEventNameForTopic:
    """Every subscribed topic maps to the event the dashboard listens for, with or without the
    env prefix; intelligence.journal is not swallowed by the shorter intelligence prefix."""

    def test_each_subscribed_topic_maps_to_its_event(self):
        expected = {
            "market.bars": "market_data",
            "market.bars.htf": "market_data",
            "intelligence": "intelligence_data",
            "intelligence.journal": "signal_scorecard",
            "signals.aggregated": "signal_data",
        }
        for env in ("", "dev"):
            topics = sse_topics(env)
            assert len(topics) == len(expected)
            for topic in topics:
                bare = topic.removeprefix(f"{env}.") if env else topic
                assert _event_name_for_topic(topic) == expected[bare], topic

    def test_an_unknown_topic_is_a_plain_message(self):
        assert _event_name_for_topic("dev.something.else") == "message"
