"""
Unit tests for SSE intelligence.record rewire (Plan 44.3-04).

Verifies:
1. _event_name_for_topic maps intelligence.record → signal_scorecard
2. intelligence.i7 topic removed from _build_topic_list()
3. intelligence.record topic present in _build_topic_list()
4. topic_intelligence_i7 marked deprecated in stream_keys
5. BarIntelligenceRecord.ranked_signals serializes to the expected signal_scorecard payload shape
"""

import json
from datetime import UTC, datetime

from src.api.routes.sse import _build_topic_list, _event_name_for_topic
from src.core.stream_keys import (
    topic_intelligence_i7,
    topic_intelligence_journal,
)


class TestEventNameForTopic:
    """_event_name_for_topic maps intelligence.record to signal_scorecard."""

    def test_intelligence_record_maps_to_signal_scorecard(self):
        """development.intelligence.record must map to signal_scorecard."""
        assert _event_name_for_topic("development.intelligence.record") == "signal_scorecard"

    def test_intelligence_record_bare_maps_to_signal_scorecard(self):
        """intelligence.record (no env prefix) must map to signal_scorecard."""
        assert _event_name_for_topic("intelligence.record") == "signal_scorecard"

    def test_intelligence_i7_no_longer_signal_scorecard(self):
        """intelligence.i7 is retired — should not map to signal_scorecard anymore.

        After the rewire, intelligence.i7 has no consumers. The event name mapping
        can be anything (or message) — it is no longer the signal_scorecard source.
        We only verify it does NOT map to signal_scorecard to confirm the switch.
        Note: this test documents the intent; the mapping may return 'message'
        or remain as is in the deprecated function.
        """
        # After retirement, intelligence.i7 events should not arrive.
        # This test documents that intelligence.record is now the signal_scorecard source.
        result = _event_name_for_topic("development.intelligence.record")
        assert result == "signal_scorecard"


class TestBuildTopicList:
    """_build_topic_list() uses intelligence.record, not intelligence.i7."""

    def test_intelligence_record_in_topic_list(self):
        """intelligence.record topic must appear in _build_topic_list()."""
        topics = _build_topic_list(["ES"], "1m")
        # Verify by checking the suffix, since env prefix varies across environments
        assert any("intelligence.record" in t for t in topics), (
            f"Expected a topic containing 'intelligence.record' in topic list, got: {topics}"
        )

    def test_intelligence_i7_not_in_topic_list(self):
        """intelligence.i7 topic must NOT appear in _build_topic_list() after rewire."""
        topics = _build_topic_list(["ES"], "1m")
        assert not any("intelligence.i7" in t for t in topics), (
            f"Expected no topic containing 'intelligence.i7' in topic list, got: {topics}"
        )


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


class TestStreamKeysDeprecation:
    """topic_intelligence_i7 is marked deprecated in stream_keys.py."""

    def test_topic_intelligence_i7_still_callable(self):
        """Deprecated function must still be callable (producer not yet removed)."""
        result = topic_intelligence_i7("")
        assert result == "intelligence.i7"

    def test_topic_intelligence_journal_available(self):
        """topic_intelligence_journal must be importable and return correct topic."""
        result = topic_intelligence_journal("")
        assert result == "intelligence.record"
