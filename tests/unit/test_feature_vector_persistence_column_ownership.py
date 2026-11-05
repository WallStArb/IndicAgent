"""Regression guard: the two regime families' column-ownership tuples (Phase 172-02).

REGIME_WRITER_OWNED_COLUMN_NAMES and REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES are the single
source of each family's columns (the kernel FAMILY_SPECS build their owned_columns from them).
These tests pin their shape and that they stay disjoint. The UPSERT exclusion they once fed was
deleted with the v1 in-place writers (todo 590).

No DB, no Kafka. Pure source introspection.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)


def test_regime_volatility_tuple_shape():
    """7-element tuple, regime_volatility first, in migration 307's declared order less the retired
    hmm_vol_prob_elevated (todo 584 D6)."""
    expected = (
        "regime_volatility",
        "hmm_vol_prob_calm",
        "hmm_vol_prob_turbulent",
        "hmm_vol_regime_prob",
        "hmm_vol_entropy",
        "hmm_vol_duration",
        "hmm_vol_churn",
    )
    assert REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES == expected
    assert len(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES) == 7


def test_regime_volatility_and_legacy_tuples_are_disjoint():
    """The two families must not share any column name -- they are separate writers
    with separate ownership, not aliases of each other."""
    overlap = set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES) & set(
        REGIME_WRITER_OWNED_COLUMN_NAMES
    )
    assert not overlap, f"Unexpected shared column name(s) between the two families: {overlap}"
