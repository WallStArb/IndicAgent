"""Tests for SSE event name routing."""
import sys
import types
from unittest.mock import MagicMock


def _import_event_name_fn():
    """Import _event_name_for_topic with minimal mocking of heavy dependencies."""
    # Provide a minimal stub for src.api.utils so sse.py can be imported
    # without triggering real settings/DB/kafka initialization
    stub_utils = types.ModuleType("src.api.utils")
    stub_utils.get_settings = MagicMock(return_value=MagicMock(env_name=""))
    stub_utils.resolve_contract = MagicMock(side_effect=lambda s: s)
    sys.modules.setdefault("src.api.utils", stub_utils)

    # Import the function fresh; clear lru_cache before each use
    from src.api.routes.sse import _event_name_for_topic
    _event_name_for_topic.cache_clear()
    return _event_name_for_topic


class TestEventNameForTopic:
    def setup_method(self):
        self.fn = _import_event_name_fn()

    def test_intelligence_journal_maps_to_signal_scorecard(self):
        assert self.fn("intelligence.journal") == "signal_scorecard"

    def test_intelligence_journal_with_env_prefix(self):
        assert self.fn("dev.intelligence.journal") == "signal_scorecard"

    def test_intelligence_maps_to_intelligence_data(self):
        assert self.fn("intelligence") == "intelligence_data"

    def test_intelligence_i8_maps_to_narrative_data(self):
        assert self.fn("intelligence.i8") == "narrative_data"

    def test_signals_aggregated_maps_to_signal_data(self):
        assert self.fn("signals.aggregated") == "signal_data"

    def test_market_bars_maps_to_market_data(self):
        assert self.fn("market.bars") == "market_data"

    def test_market_bars_htf_maps_to_market_data(self):
        assert self.fn("market.bars.htf") == "market_data"

    def test_narratives_maps_to_narrative_data(self):
        assert self.fn("narratives") == "narrative_data"

    def test_narratives_group_maps_to_narrative_data(self):
        assert self.fn("narratives.group") == "narrative_data"

    def test_intelligence_other_subtopic_maps_to_intelligence_data(self):
        """intelligence.anything (not journal/record/i7/i8) stays as intelligence_data."""
        assert self.fn("intelligence.someotherthing") == "intelligence_data"


class TestBuildTopicList:
    def _get_topics(self):
        from unittest.mock import MagicMock, patch
        mock_settings = MagicMock()
        mock_settings.env_name = ""
        with patch("src.api.routes.sse._get_settings", return_value=mock_settings):
            from src.api.routes.sse import _build_topic_list
            return _build_topic_list(["ES"], "1m")

    def test_no_dead_indicators_topic(self):
        """indicators topic has no active producer — must not be in SSE subscription list."""
        topics = self._get_topics()
        assert "indicators" not in topics, "indicators topic has no active producer"

    def test_no_dead_market_ticks_topic(self):
        """market.ticks has no active publisher — must not be in SSE subscription list."""
        topics = self._get_topics()
        assert "market.ticks" not in topics, "market.ticks has no publisher for SSE"

    def test_active_topics_present(self):
        """Core active topics must be in SSE subscription list."""
        topics = self._get_topics()
        for expected in [
            "market.bars",
            "market.bars.htf",
            "intelligence",
            "intelligence.journal",
            "intelligence.i8",
            "signals.aggregated",
            "narratives",
            "narratives.group",
        ]:
            assert expected in topics, f"{expected} missing from topic list"
