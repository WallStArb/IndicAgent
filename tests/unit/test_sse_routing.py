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
