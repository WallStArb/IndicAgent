"""Unit tests for services.ensemble_trainer._get_feature_columns (Phase 172-02,
extended 2026-08-12 for todo 287).

No test file covered _get_feature_columns before Phase 172-02 -- this is new
coverage, not an extension of pre-existing tests. Verifies the training-matrix
exclusion for both regime column families:

- regime_volatility (migration 307, 8 columns) -- original coverage.
- legacy regime family (REGIME_WRITER_OWNED_COLUMN_NAMES, 8 columns) -- todo 287,
  2026-08-12: only 4 of these 8 (regime/hmm_regime_prob/hmm_entropy/hmm_duration)
  were ever excluded; hmm_prob_trending_up/hmm_prob_ranging/hmm_prob_trending_down/
  hmm_churn leaked into the training matrix and got silently 0.0-imputed for every
  partially-labeled row since the columns existed. This file's original
  test_legacy_meta_columns_still_excluded only stubbed the 4 protected columns, so
  it could not have caught the leak -- fixed here by stubbing and asserting on the
  full 8-column family via the same shared constant the fix now uses.

Both families are written by the same partial-coverage UPDATE pass (warmup prefix
bars, degenerate segments never get a label) -- a NULL there is not "no signal"
and must not be silently imputed to 0.0 downstream.

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
    REGIME_WRITER_OWNED_COLUMN_NAMES,
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
    {"column_name": "regime_label_source"},
    {"column_name": "created_at"},
    # ordinary feature columns -- must survive the filter
    {"column_name": "realized_vol"},
    {"column_name": "momentum_z_fast"},
]
_STUB_COLUMNS += [{"column_name": name} for name in REGIME_WRITER_OWNED_COLUMN_NAMES]
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
    """Pre-existing exclusions (PK/metadata) must remain excluded -- the new
    addition must not have replaced them."""
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
        "regime_label_source",
        "created_at",
    ):
        assert name not in cols, f"{name} should remain excluded from the feature matrix"


@pytest.mark.asyncio
async def test_legacy_regime_family_fully_excluded_from_feature_matrix():
    """Todo 287 regression pin: all 8 REGIME_WRITER_OWNED_COLUMN_NAMES members must
    be excluded, not just the 4 (regime/hmm_regime_prob/hmm_entropy/hmm_duration)
    this codebase protected before the fix. hmm_prob_trending_up/hmm_prob_ranging/
    hmm_prob_trending_down/hmm_churn are written by the exact same partial-coverage
    UPDATE pass as the other 4 -- leaking them fabricates a 0.0 trend-probability/
    churn value for every row regime_writer.py hasn't labeled yet."""
    conn = _FakeConnection(_STUB_COLUMNS)
    cols = await _get_feature_columns(conn)
    overlap = set(cols) & set(REGIME_WRITER_OWNED_COLUMN_NAMES)
    assert not overlap, (
        f"_get_feature_columns() leaked legacy regime column(s) {overlap} into the "
        f"training feature matrix -- a NULL there would be silently imputed to 0.0, "
        f"fabricating signal for unlabeled/partially-covered bars (todo 287)"
    )
