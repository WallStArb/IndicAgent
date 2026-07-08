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
    feature_vector_to_insert_params,
)
from src.intelligence.schemas import FeatureVector

_ALL_FEATURE_FIELDS = [f.name for f in dataclasses.fields(FeatureVector)]


def _sql_column_names() -> list[str]:
    """Extract the column name list (in order, duplicates included) from the
    INSERT INTO ... ( ... ) clause."""
    match = re.search(
        r"INSERT INTO feature_vectors \((.*?)\)\s*VALUES", FEATURE_VECTOR_INSERT_SQL, re.DOTALL
    )
    assert match, "Could not parse column list from FEATURE_VECTOR_INSERT_SQL"
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
