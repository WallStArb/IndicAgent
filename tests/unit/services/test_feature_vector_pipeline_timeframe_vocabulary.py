"""Regression test for todo 327 — self._timeframes reads CVR's `timeframe`
namespace via src.core.timeframe_vocabulary, not the hardcoded module-level
_STANDARD_TFS tuple that used to be assigned in __init__.

No existing test in this test-file family exercises FeatureVectorPipeline._setup()
as a whole (it requires mocking Kafka/DB-init/ConfigService end to end, noted as
out of scope in test_feature_vector_pipeline_cross_asset.py's
test_setup_load_failure_leaves_series_empty_not_crashed docstring), so this test
exercises the extracted _prewarm_timeframe_vocabulary() method directly — the same
narrow-method-under-test pattern already used for _load_cross_asset_series() and
_refresh_cross_asset_series() in test_feature_vector_pipeline_cross_asset.py.
"""

from __future__ import annotations

import pytest

import services.feature_vector_pipeline as fvp_module
from src.core import timeframe_vocabulary
from tests.unit._vocabulary_fakes import FakeVocabularyService
from tests.unit.pipeline.pipeline_helpers import make_agent


@pytest.fixture(autouse=True)
def _reset_vocab():
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    yield
    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.unit
async def test_setup_prewarms_timeframe_vocabulary(monkeypatch):
    """_prewarm_timeframe_vocabulary() registers a VocabularyService with
    timeframe_vocabulary so self._timeframes reflects CVR's registered set,
    not the hardcoded default."""
    # Deliberately differs from the old hardcoded _STANDARD_TFS tuple (adds
    # "30m"), so a passing assertion proves the value came from the registry, not
    # a stale fallback. Patched on timeframe_vocabulary -- prewarm() constructs
    # VocabularyService there now, not in feature_vector_pipeline's own module.
    monkeypatch.setattr(
        timeframe_vocabulary,
        "VocabularyService",
        FakeVocabularyService(["1m", "5m", "15m", "30m", "1h", "4h", "1d"]),
    )
    agent = make_agent()

    assert timeframe_vocabulary._vocab_service is None

    await agent._prewarm_timeframe_vocabulary()

    assert timeframe_vocabulary._vocab_service is agent._vocabulary_service
    assert agent._vocabulary_service.initialized is True
    assert agent._timeframes == ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


@pytest.mark.unit
def test_standard_tfs_module_constant_removed():
    """_STANDARD_TFS must no longer exist at module level — timeframe_vocabulary
    is the sole source of the standard timeframe set now (todo 327)."""
    assert not hasattr(fvp_module, "_STANDARD_TFS")
