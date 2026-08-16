"""Regression tests for todo 327 — BarWriter._bars_written_attrs is built from CVR's
`timeframe` namespace via src.core.timeframe_vocabulary, not the hardcoded module-level
_BAR_TFS tuple that used to be read eagerly in __init__.

__init__ must stay synchronous (no VocabularyService dependency), so
_bars_written_attrs starts empty there and is populated by a new
_prewarm_timeframe_vocabulary() method called from _setup(). No existing test in this
file exercises BarWriter._setup() end to end (it wires create_db_pool, a retrying
contract-cache load, and a live Kafka consumer), so this test exercises
_prewarm_timeframe_vocabulary() directly via the same __new__-bypass agent pattern
test_bar_writer.py's _make_agent() already uses — matching Task 3's
(feature_vector_pipeline.py) narrow-method-under-test precedent for this same todo.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import services.bar_writer as bar_writer_module
from src.core import timeframe_vocabulary


class _FakeVocabularyService:
    """Stands in for VocabularyService — records initialize() and reports a
    CVR-registered set that deliberately differs from the old hardcoded _BAR_TFS
    tuple, so a passing assertion proves the value came from here, not a stale
    fallback."""

    def __init__(self, database_url, pool=None):
        self.database_url = database_url
        self.pool = pool
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    def active_codes(self, namespace: str) -> list[str]:
        assert namespace == "timeframe"
        return ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


def _make_bare_agent():
    """Build BarWriter using __new__ (bypasses __init__, matches
    test_bar_writer.py's _make_agent() pattern) with just enough attributes for
    _prewarm_timeframe_vocabulary()."""
    from services.bar_writer import BarWriter

    agent = BarWriter.__new__(BarWriter)
    agent.name = "bar_writer_agent"
    agent.logger = MagicMock()
    agent.settings = MagicMock(database_url="postgresql://test")
    agent._db_pool = MagicMock()
    agent._bars_written_attrs = {}
    agent._vocabulary_service = None
    return agent


@pytest.fixture(autouse=True)
def _reset_vocab():
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    yield
    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.unit
def test_init_does_not_require_vocabulary_service():
    """__init__ must not crash before any async setup has run -- confirms the OTel
    attrs dict construction moved out of __init__."""
    from services.bar_writer import BarWriter

    writer = BarWriter()  # must not raise, must not touch VocabularyService
    assert writer._bars_written_attrs == {}


@pytest.mark.unit
async def test_prewarm_timeframe_vocabulary_builds_bars_written_attrs(monkeypatch):
    """_prewarm_timeframe_vocabulary() registers a VocabularyService with
    timeframe_vocabulary and rebuilds _bars_written_attrs from CVR's registered
    codes, not the removed hardcoded tuple."""
    monkeypatch.setattr(bar_writer_module, "VocabularyService", _FakeVocabularyService)
    agent = _make_bare_agent()

    assert timeframe_vocabulary._vocab_service is None

    await agent._prewarm_timeframe_vocabulary()

    assert timeframe_vocabulary._vocab_service is agent._vocabulary_service
    assert agent._vocabulary_service.initialized is True
    assert set(agent._bars_written_attrs.keys()) == {
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
    }
    assert agent._bars_written_attrs["30m"] == {"agent": "bar_writer_agent", "tf": "30m"}


@pytest.mark.unit
def test_bar_tfs_module_constant_removed():
    """_BAR_TFS must no longer exist at module level -- timeframe_vocabulary is the
    sole source of the standard timeframe set now (todo 327)."""
    assert not hasattr(bar_writer_module, "_BAR_TFS")
