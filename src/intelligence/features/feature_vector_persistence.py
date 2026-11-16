"""Persistence contracts for feature rows: the feature_vectors row contract.

The table is written only by services/backfill_feature_factory.py through bulk_load(); its
column list (`FEATURE_VECTORS_COLUMNS`) is derived from the kernel registry, never typed, and
`feature_vector_row_values` is the one row constructor for it. This module also holds the
regime families' column ownership (`REGIME_WRITER_OWNED_COLUMN_NAMES`,
`REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES`) and the FeatureVector field-name tuple the ops
scripts read.

2026-11-04 (migration 570, todo 584 item 3): the table built under the name feature_vectors_v2
took the name feature_vectors and the v1 table was dropped.

2026-11-16 (R2 item 5b): the legacy v1 row contract of the retired streaming writer (the
307-column INSERT SQL, `feature_vector_to_insert_params`, `make_feature_vector_id`,
`validate_feature_vector`, the derived column slices) was deleted with the streaming
FeatureFactory. Git history before this date holds it; the history of the column additions
(migrations 206 to 350) lives in the migration headers.

Ring 1: imports FeatureVector from src.intelligence.features.feature_vector.
Do not import from Ring 2 (services/) or Ring 3 (api/, production/).
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Sequence
from datetime import datetime

from src.intelligence.features.feature_vector import FeatureVector

# The FeatureVector field names in dataclass order; ops scripts read the measured-column order
# from here (ic_measure takes its own from dataclasses.fields(FeatureVector) directly).
_ALL_FEATURE_VECTOR_FIELD_NAMES: tuple[str, ...] = tuple(
    f.name for f in dataclasses.fields(FeatureVector)
)


# Single source of truth for the trend regime family's column ownership (Ring 1, this module);
# the kernel FAMILY_SPECS build their owned_columns from it, so the list cannot drift. The v1
# in-place writer of these columns and its --refresh UPSERT exclusion (the 2026-07-30 incident that
# nulled feature_vectors.regime) were retired in todo 590; git history holds the full account.
REGIME_WRITER_OWNED_COLUMN_NAMES: tuple[str, ...] = (
    "regime",
    "hmm_prob_trending_up",
    "hmm_prob_ranging",
    "hmm_prob_trending_down",
    "hmm_regime_prob",
    "hmm_entropy",
    "hmm_duration",
    "hmm_churn",
)

# Single source of truth for the regime_volatility family's column ownership (Ring 1, this
# module, same rule as REGIME_WRITER_OWNED_COLUMN_NAMES above).
REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES: tuple[str, ...] = (
    "regime_volatility",
    "hmm_vol_prob_calm",
    "hmm_vol_prob_turbulent",
    "hmm_vol_regime_prob",
    "hmm_vol_entropy",
    "hmm_vol_duration",
    "hmm_vol_churn",
)

# ---------------------------------------------------------------------------
# feature_vectors row contract (phase 186 plan 25, D-28)
# ---------------------------------------------------------------------------

# Registry feature columns the table does not carry (186-24 migration 425, proofs in
# .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/
# 186-24-feature-vectors-v2-schema.json). tests/unit/intelligence/test_feature_vectors_rows.py
# pins this tuple to that evidence file and to the migration. days_to_month_end is inside the
# registry's feature_columns() and so must be excluded here; the three rank columns (retired from
# the registry and the FeatureVector, todo 558) were never in feature_columns(), so they never
# appear in the derivation below.
FEATURE_VECTORS_DROPPED_FEATURE_COLUMNS: frozenset[str] = frozenset(
    {
        "momentum_rank_z",
        "volume_rank_z",
        "volatility_rank_z",
        "regime_rolling",
        "days_to_month_end",
    }
)

FEATURE_VECTORS_KEY_COLUMNS: tuple[str, ...] = ("symbol", "tf", "bar_ts")
FEATURE_VECTORS_TEXT_COLUMNS: tuple[str, ...] = ("regime", "regime_volatility")


@functools.cache
def feature_vectors_numeric_columns() -> tuple[str, ...]:
    """The numeric (real) columns of feature_vectors, in registry order (`feature_columns()`
    is sorted by name), minus the dropped set and the two regime text outputs.

    The registry is imported here, not at module import: a kernel module (`_hmm`) imports this
    module, so a module-level `default_registry()` call would be a circular import.
    """
    from src.intelligence.features.contract.registry import default_registry

    skip = FEATURE_VECTORS_DROPPED_FEATURE_COLUMNS | set(FEATURE_VECTORS_TEXT_COLUMNS)
    return tuple(c for c in default_registry().feature_columns() if c not in skip)


@functools.cache
def feature_vectors_columns() -> tuple[str, ...]:
    """Column order of the feature_vectors rows the writer builds: keys, the two regime text
    columns, then the numeric columns in registry order. Migration 425 created the table in this
    order; columns a later migration adds (526) sit last physically, which is harmless because
    the writer COPYs with this explicit column list."""
    return (
        *FEATURE_VECTORS_KEY_COLUMNS,
        *FEATURE_VECTORS_TEXT_COLUMNS,
        *feature_vectors_numeric_columns(),
    )


def feature_vectors_output_columns() -> tuple[str, ...]:
    """The non-key columns of feature_vectors (the two regime text outputs plus the numeric
    columns): what a compute pass must produce for the table. Derived from the key-column
    constant, never a hard-coded offset, so a key-column change cannot silently shift it."""
    return feature_vectors_columns()[len(FEATURE_VECTORS_KEY_COLUMNS) :]


def __getattr__(name: str) -> tuple[str, ...]:
    # Lazy module attribute (PEP 562): `from ... import FEATURE_VECTORS_COLUMNS` works and
    # resolves the registry on first use, never at import (see feature_vectors_numeric_columns).
    if name == "FEATURE_VECTORS_COLUMNS":
        return feature_vectors_columns()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def feature_vector_row_values(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    regime: str | None,
    regime_volatility: str | None,
    numeric_values: Sequence[float],
) -> tuple:
    """One feature_vectors row in `feature_vectors_columns()` order.

    `numeric_values` are the numeric columns in `feature_vectors_numeric_columns()` order. A
    NaN is missing data (no_fill: a warmup row, a macro column before the first daily record, a
    column a mask marks None) and is written as None, so the COPY stores NULL and never the text
    NaN. An infinite value is kept as it is (a loud value downstream, not a silent NULL).
    """
    n_numeric = len(feature_vectors_numeric_columns())
    if len(numeric_values) != n_numeric:
        raise ValueError(
            f"feature_vector_row_values: got {len(numeric_values)} numeric values, "
            f"the table has {n_numeric}"
        )
    return (
        symbol,
        tf,
        bar_ts,
        regime,
        regime_volatility,
        *(None if v != v else v for v in numeric_values),
    )
