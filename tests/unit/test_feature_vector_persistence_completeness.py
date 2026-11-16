"""The regime families' column ownership in feature_vector_persistence.py is the single list the
kernel family specs build their owned columns from.

The kernel family specs used to hold an independent hand-typed literal, the two-lists-drift
failure mode behind the 2026-07-08 incident (91 of 152 feature columns written as NULL). The
identity check below fails loud if a spec ever holds its own copy that drifts. The streaming
INSERT contract that the original completeness checks guarded was deleted in R2 item 5b; the
table's column set is now derived from the kernel registry
(tests/unit/intelligence/test_kernel_registry.py pins it to the FeatureVector schema).

No DB, no Kafka.
"""

from __future__ import annotations

from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.features.kernels._hmm import FAMILY_SPECS


def test_regime_family_owned_columns_derive_from_the_canonical_tuples():
    assert FAMILY_SPECS["trend"].owned_columns == REGIME_WRITER_OWNED_COLUMN_NAMES
    assert FAMILY_SPECS["volatility"].owned_columns == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES
