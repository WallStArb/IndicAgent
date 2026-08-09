"""Unit tests for services.ensemble_trainer._get_feature_columns (Phase 172-02).

No test file covered _get_feature_columns before this one -- this is new coverage,
not an extension. Verifies the training-matrix exclusion for the new
regime_volatility column family (migration 307): none of its 8 columns may reach
EnsembleTrainer's training feature matrix, because coverage is inherently partial
(the walk-forward labeling path writes nothing for warmup prefix bars or degenerate
segments) -- a NULL there is not "no signal" and must not be silently imputed to
0.0 downstream, the same reasoning already applied to hmm_regime_prob/hmm_entropy/
hmm_duration.

No DB, no Kafka -- a fake asyncpg connection whose fetch() returns a static list of
mapping-like rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_trainer import _get_feature_columns
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
)

# A representative slice of feature_vectors.information_schema.columns: PK/metadata
# columns, the legacy regime family, the new regime_volatility family, and a couple
# of ordinary numeric feature columns that must survive the filter.
_STUB_COLUMNS = [
    {"column_name": "id"},
    {"column_name": "symbol"},
    {"column_name": "tf"},
    {"column_name": "bar_ts"},
    {"column_name": "bar_close_ts"},
    {"column_name": "feature_factory_version"},
    {"column_name": "feature_vector_id"},
    {"column_name": "pipeline_version"},
    {"column_name": "regime"},
    {"column_name": "regime_label_source"},
    {"column_name": "created_at"},
    {"column_name": "hmm_regime_prob"},
    {"column_name": "hmm_entropy"},
    {"column_name": "hmm_duration"},
    # ordinary feature columns -- must survive the filter
    {"column_name": "realized_vol"},
    {"column_name": "momentum_z_fast"},
]
_STUB_COLUMNS += [{"column_name": name} for name in REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES]


class _FakeConnection:
    """Minimal asyncpg.Connection stand-in: only .fetch() is exercised."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetch(self, _query: str):
        return self._rows


@pytest.mark.asyncio
async def test_regime_volatility_columns_excluded_from_feature_matrix():
    """None of the 8 regime_volatility columns may appear in the returned list --
    this is the primary invariant this test file exists to pin."""
    conn = _FakeConnection(_STUB_COLUMNS)
    cols = await _get_feature_columns(conn)
    overlap = set(cols) & set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
    assert not overlap, (
        f"_get_feature_columns() leaked regime_volatility column(s) {overlap} into "
        f"the training feature matrix -- a NULL there would be silently imputed to "
        f"0.0, fabricating signal for warmup/degenerate bars"
    )


@pytest.mark.asyncio
async def test_ordinary_feature_columns_survive_the_filter():
    """A control column not in any exclusion list must still be returned -- proves
    the filter is targeted, not accidentally over-broad."""
    conn = _FakeConnection(_STUB_COLUMNS)
    cols = await _get_feature_columns(conn)
    assert "realized_vol" in cols
    assert "momentum_z_fast" in cols


@pytest.mark.asyncio
async def test_legacy_meta_columns_still_excluded():
    """Pre-existing exclusions (PK/metadata + legacy regime family) must remain
    excluded -- the new addition must not have replaced them."""
    conn = _FakeConnection(_STUB_COLUMNS)
    cols = await _get_feature_columns(conn)
    for name in (
        "id",
        "symbol",
        "tf",
        "bar_ts",
        "bar_close_ts",
        "feature_factory_version",
        "feature_vector_id",
        "pipeline_version",
        "regime",
        "regime_label_source",
        "created_at",
        "hmm_regime_prob",
        "hmm_entropy",
        "hmm_duration",
    ):
        assert name not in cols, f"{name} should remain excluded from the feature matrix"
