"""The dormant pipeline reads the kernel registry (186-15, D-28).

A numeric FeatureVector column with no registry kernel and no UNOWNED_COLUMNS entry stops the
daemon at startup: a column the live path publishes that no kernel computes is a train-serve
skew, and a silent one. The startup guard is a static method so it runs without a database;
`make_agent` bypasses `_prewarm_threshold_config`, so the guard is tested directly.
"""

from __future__ import annotations

import json

import pytest

from services import feature_vector_pipeline as pipeline_module
from services.feature_vector_pipeline import FeatureVectorPipeline
from src.intelligence.features.contract.registry import UNOWNED_COLUMNS, registry_column_gaps
from src.intelligence.features.feature_vector_persistence import NUMERIC_COLUMN_NAMES
from tests.unit.intelligence import kernel_parity_reference as ref


def test_a_clean_start_passes_the_ownership_check():
    FeatureVectorPipeline._require_registry_column_ownership()  # does not raise


def test_an_extra_numeric_column_stops_the_start(monkeypatch):
    monkeypatch.setattr(
        pipeline_module, "NUMERIC_COLUMN_NAMES", (*NUMERIC_COLUMN_NAMES, "brand_new_feature")
    )
    with pytest.raises(RuntimeError, match="brand_new_feature"):
        FeatureVectorPipeline._require_registry_column_ownership()


def test_the_gap_helper_names_every_unowned_column_once():
    assert registry_column_gaps(["ret_lag_1", "nope_b", "nope_a"]) == ["nope_a", "nope_b"]
    assert registry_column_gaps(list(UNOWNED_COLUMNS)) == []


def test_the_numeric_schema_equals_the_parity_manifests():
    """NUMERIC_COLUMN_NAMES is what the golden fixture calls numeric; they drifting apart would
    make the startup check and the golden disagree about which columns exist."""
    manifest = json.loads((ref.FIXTURE_DIR / "manifest.json").read_text())
    assert set(NUMERIC_COLUMN_NAMES) == set(manifest["numeric_columns"])


def test_supported_timeframes_pass_the_startup_check():
    FeatureVectorPipeline._require_supported_timeframes(["5m", "15m", "1h", "4h", "1d"])
    FeatureVectorPipeline._require_supported_timeframes(["1m"])


def test_an_unsupported_timeframe_stops_the_start_naming_it():
    """The live cross-asset lookup raises per bar for a timeframe the as-of rule has no bar
    duration for; the start fails first, with the timeframe in the message."""
    with pytest.raises(ValueError, match="'7m'"):
        FeatureVectorPipeline._require_supported_timeframes(["5m", "7m", "1d"])


@pytest.mark.asyncio
async def test_the_vocabulary_prewarm_applies_the_check(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    agent = FeatureVectorPipeline.__new__(FeatureVectorPipeline)
    agent.settings = SimpleNamespace(database_url="x")
    agent._db = SimpleNamespace(pool=None)
    monkeypatch.setattr(pipeline_module.vocabulary_access, "prewarm", AsyncMock(return_value=None))
    monkeypatch.setattr(
        pipeline_module.vocabulary_access, "standard_timeframes", lambda: ["5m", "9m"]
    )
    with pytest.raises(ValueError, match="'9m'"):
        await agent._prewarm_timeframe_vocabulary()
