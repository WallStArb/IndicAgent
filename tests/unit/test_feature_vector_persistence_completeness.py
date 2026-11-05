"""Regression guard: every FeatureVector dataclass field must be persisted.

Root cause this prevents (found 2026-07-08): Phase 142.5 added 91 new primitive
fields to the FeatureVector dataclass and the feature_vectors DB schema
(migration 206), with compute logic fully wired and unit-tested. But
feature_vector_persistence.py's canonical INSERT contract -- the single choke
point both the live (FeatureVectorWriter) and batch (backfill_feature_factory)
write paths import from -- was never updated to include them. The values were
computed correctly in memory, then silently discarded before ever reaching the
database: 91 of 152 feature columns (60%) were 100% NULL across the entire
36M-row corpus, indistinguishable from "no predictive signal" in every
downstream IC measurement. This was a documented, deliberately-deferred gap
(test_feature_vector_writer_column_mapping.py's sentinel test explicitly
comments "not yet in the persisted tuple... wiring lands in a later plan" for
every affected field) that fell through the cracks -- no todo tracked closing
it before the next corpus rebuild ran.

This test makes that specific failure mode structurally impossible to ship
silently again: it fails loud the moment FeatureVector gains a field that
FEATURE_VECTOR_INSERT_SQL/feature_vector_to_insert_params() doesn't know
about, rather than waiting for a downstream measurement result to look
suspiciously weak.

No DB, no Kafka. Pure source/dataclass introspection.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.intelligence.features.feature_vector_persistence import (
    FEATURE_VECTOR_INSERT_SQL,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
    feature_vector_to_insert_params,
)
from src.intelligence.schemas import FeatureVector

_ALL_FEATURE_FIELDS = [f.name for f in dataclasses.fields(FeatureVector)]


def _sql_column_names(sql: str = FEATURE_VECTOR_INSERT_SQL) -> list[str]:
    """Extract the column name list (in order, duplicates included) from the
    INSERT INTO ... ( ... ) clause."""
    match = re.search(r"INSERT INTO feature_vectors \((.*?)\)\s*VALUES", sql, re.DOTALL)
    assert match, "Could not parse column list from SQL"
    raw = match.group(1)
    return [c.strip() for c in raw.split(",") if c.strip()]


def test_every_feature_vector_field_is_a_sql_column():
    """Every FeatureVector dataclass field must appear as an INSERT column.

    This is the exact invariant that was silently violated for 91/152 fields
    (Phase 142.5's Renaissance primitives) -- catches the next such gap
    immediately instead of after a full corpus rebuild.
    """
    sql_columns = set(_sql_column_names())
    missing = [f for f in _ALL_FEATURE_FIELDS if f not in sql_columns]
    assert not missing, (
        f"{len(missing)} FeatureVector field(s) are missing from "
        f"FEATURE_VECTOR_INSERT_SQL and will be silently dropped on every "
        f"write: {missing}"
    )


def test_sql_column_count_matches_placeholder_count():
    """Column list length must equal $N placeholder count -- a mismatch here
    means a positional misalignment that would silently write the wrong
    value into the wrong column."""
    n_columns = len(set(_sql_column_names()))
    n_placeholders = len(re.findall(r"\$\d+", FEATURE_VECTOR_INSERT_SQL))
    assert (
        n_columns == n_placeholders
    ), f"Column count ({n_columns}) != placeholder count ({n_placeholders})"


def test_insert_params_tuple_length_matches_sql():
    """feature_vector_to_insert_params() must return exactly as many elements
    as FEATURE_VECTOR_INSERT_SQL has placeholders."""
    from datetime import UTC, datetime

    kwargs = {f: 0.0 for f in _ALL_FEATURE_FIELDS}
    vector = FeatureVector(**kwargs)
    params = feature_vector_to_insert_params(
        symbol="SPY",
        tf="1h",
        bar_ts=datetime(2026, 1, 1, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="trending_up",
        regime_label_source="filtered",
        vector=vector,
    )
    n_placeholders = len(re.findall(r"\$\d+", FEATURE_VECTOR_INSERT_SQL))
    assert len(params) == n_placeholders, (
        f"feature_vector_to_insert_params() returned {len(params)} elements, "
        f"expected {n_placeholders} to match FEATURE_VECTOR_INSERT_SQL"
    )


def test_no_duplicate_sql_columns():
    """A field listed twice would silently bind two different tuple values
    to the same column, corrupting whichever one loses."""
    names = _sql_column_names()
    assert len(names) == len(set(names)), "Duplicate column name in FEATURE_VECTOR_INSERT_SQL"


# ── Cross-module ownership identity (todo 205 follow-up, 2026-07-30) ──────────
#
# regime_writer.py's set_cols used to be an independent hand-typed literal --
# exactly the two-lists-drift failure mode this module's own docstring already
# documents for FeatureVector fields (2026-07-08). Fixed by having
# regime_writer.py import REGIME_WRITER_OWNED_COLUMN_NAMES from this module
# instead of defining its own copy. This test verifies the import wiring is
# actually in place (not just that someone happened to type the same 8 names
# twice) -- an identity check, not a value-equality check, so a revert to a
# hand-typed literal fails loud even if the literal's values still match today.


def test_regime_writer_set_cols_derive_from_the_canonical_tuples():
    """The writer's UPDATE set_cols are each family spec's `owned_columns`, which the spec builds
    from REGIME_WRITER_OWNED_COLUMN_NAMES (and the volatility tuple) in this module. Value
    equality with those tuples fails loud if the spec table ever holds its own literal that
    drifts from the ownership lists this module's DO UPDATE SET exclusion uses."""
    from src.intelligence.features.feature_vector_persistence import (
        REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    )
    from src.intelligence.features.kernels._hmm import FAMILY_SPECS

    assert FAMILY_SPECS["trend"].owned_columns == REGIME_WRITER_OWNED_COLUMN_NAMES
    assert FAMILY_SPECS["volatility"].owned_columns == REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES


# ── Real-column underflow clamp (underflow-7symbol-real-column debug session,
# 2026-09-22) ───────────────────────────────────────────────────────────────
#
# feature_vector_to_insert_params() is the single shared row-serializer for both the
# live asyncpg write path (FeatureVectorWriter) and the batch psycopg write path
# (backfill_feature_factory) -- it never clamped a `real`-typed float to what Postgres's
# `real` (float4) column can represent, unlike services/_batch_utils.py's
# bulk_update_by_key (todo 312). A feature value with magnitude smaller than float4's
# smallest subnormal (e.g. a highly-confident HMM posterior probability residual) made
# Postgres reject the whole INSERT batch with "value out of range: underflow",
# permanently stalling BIL/VRP/ENPH/GLD/NAD/SHY/STIP's backfills at 40-90% coverage.


def test_insert_params_clamps_underflowing_float_to_zero():
    """A real-typed feature value smaller in magnitude than float4 can represent must be
    clamped to 0.0 in the returned tuple, not passed through to hit Postgres's underflow
    rejection."""
    from datetime import UTC, datetime

    kwargs = {f: 0.0 for f in _ALL_FEATURE_FIELDS}
    kwargs["hmm_regime_prob"] = 1e-50
    kwargs["hmm_entropy"] = -1e-60
    vector = FeatureVector(**kwargs)
    params = feature_vector_to_insert_params(
        symbol="BIL",
        tf="5m",
        bar_ts=datetime(2026, 1, 1, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="trending_up",
        regime_label_source="filtered",
        vector=vector,
    )
    names = _sql_column_names()
    prob_value = params[names.index("hmm_regime_prob")]
    entropy_value = params[names.index("hmm_entropy")]
    assert prob_value == 0.0
    assert entropy_value == 0.0


def test_insert_params_clamps_overflowing_float_to_real_max():
    """A real-typed feature value larger in magnitude than float4 can represent must be
    clamped to float4 max (symmetric defensive coverage, same as bulk_update_by_key)."""
    from datetime import UTC, datetime

    from src.core.real_column_range import REAL_MAX_MAGNITUDE

    kwargs = {f: 0.0 for f in _ALL_FEATURE_FIELDS}
    kwargs["hmm_regime_prob"] = 1e50
    vector = FeatureVector(**kwargs)
    params = feature_vector_to_insert_params(
        symbol="BIL",
        tf="5m",
        bar_ts=datetime(2026, 1, 1, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="trending_up",
        regime_label_source="filtered",
        vector=vector,
    )
    names = _sql_column_names()
    prob_value = params[names.index("hmm_regime_prob")]
    assert prob_value == REAL_MAX_MAGNITUDE


def test_insert_params_leaves_ordinary_values_untouched():
    """A well-formed value already inside float4's representable range must not be
    mutated by the clamp -- e.g. must not be coerced to a different float or type."""
    from datetime import UTC, datetime

    kwargs = {f: 0.0 for f in _ALL_FEATURE_FIELDS}
    kwargs["hmm_regime_prob"] = 0.42
    vector = FeatureVector(**kwargs)
    params = feature_vector_to_insert_params(
        symbol="BIL",
        tf="5m",
        bar_ts=datetime(2026, 1, 1, tzinfo=UTC),
        pipeline_version="3.0.0",
        feature_factory_version="1.0.0",
        regime="trending_up",
        regime_label_source="filtered",
        vector=vector,
    )
    names = _sql_column_names()
    prob_value = params[names.index("hmm_regime_prob")]
    assert prob_value == 0.42
    # Structural columns (non-float) must survive the clamp map untouched.
    assert params[names.index("symbol")] == "BIL"
    assert params[names.index("regime")] == "trending_up"
