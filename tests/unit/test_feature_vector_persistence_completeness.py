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
    FEATURE_VECTOR_INSERT_SQL_PSYCOPG,
    FEATURE_VECTOR_UPSERT_SQL,
    FEATURE_VECTOR_UPSERT_SQL_PSYCOPG,
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


# ── FEATURE_VECTOR_UPSERT_SQL (todo 176 fix, added 2026-07-27) ────────────────
#
# ON CONFLICT (symbol, tf, bar_ts) DO NOTHING (the INSERT variant) silently
# skips any re-insert of a bar that already exists -- confirmed as the reason
# a naive backfill re-run never populated Phase 163's 17 VP/SR columns on
# 36.7M pre-existing rows. FEATURE_VECTOR_UPSERT_SQL is the recompute/backfill
# escape hatch (DO UPDATE SET every non-PK column); these tests hold it to the
# same structural invariants as the INSERT variant above, plus the specific
# property that makes it useful: every column actually gets overwritten.


def test_upsert_has_same_column_list_as_insert():
    """The two statements must stay column-for-column identical -- an upsert
    that silently drops a column while the insert doesn't would reintroduce
    exactly the failure class this module's docstring already documents."""
    assert _sql_column_names(FEATURE_VECTOR_UPSERT_SQL) == _sql_column_names(
        FEATURE_VECTOR_INSERT_SQL
    )


def test_upsert_column_count_matches_placeholder_count():
    n_columns = len(set(_sql_column_names(FEATURE_VECTOR_UPSERT_SQL)))
    n_placeholders = len(re.findall(r"\$\d+", FEATURE_VECTOR_UPSERT_SQL))
    assert (
        n_columns == n_placeholders
    ), f"Column count ({n_columns}) != placeholder count ({n_placeholders})"


def test_upsert_params_tuple_length_matches_sql():
    """Same serializer feeds both statements -- must line up with the upsert's
    placeholder count too, not just the insert's."""
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
    n_placeholders = len(re.findall(r"\$\d+", FEATURE_VECTOR_UPSERT_SQL))
    assert len(params) == n_placeholders


# Mirrors feature_vector_persistence._EXTERNALLY_OWNED_COLUMN_NAMES. Deliberately not
# imported: these tests pin the two names independently of the module's own exclusion
# set, so a mistaken edit to the source frozenset still fails loud here instead of the
# test becoming tautological against the thing it's checking.
_EXTERNALLY_OWNED_COLUMNS = {
    "regime",
    "regime_label_source",
    "hmm_regime_prob",
    "hmm_entropy",
    "hmm_duration",
}
_NEVER_UPDATED_COLUMNS = {"symbol", "tf", "bar_ts"} | _EXTERNALLY_OWNED_COLUMNS


def _upsert_set_columns() -> list[str]:
    """Column names on the left of `= EXCLUDED.<same>` in DO UPDATE SET, in order."""
    match = re.search(r"DO UPDATE SET\s*(.*?)\s*\Z", FEATURE_VECTOR_UPSERT_SQL, re.DOTALL)
    assert match, "Could not parse DO UPDATE SET clause"
    return re.findall(r"(\w+)\s*=\s*EXCLUDED\.\1", match.group(1))


def test_upsert_updates_every_non_pk_column_exactly_once():
    """DO UPDATE SET must cover every column except the (symbol, tf, bar_ts)
    conflict target and columns owned by a different writer -- a column
    silently missing from SET would keep its old (possibly NULL, pre-fix)
    value forever on every future recompute, the exact bug this statement
    exists to close.

    _EXTERNALLY_OWNED_COLUMNS are deliberately excluded: they're owned by
    regime_writer.py's separate UPDATE pass, not by whatever caller builds
    this row. Including regime was the actual root cause of the 2026-07-30
    incident (a --refresh run nulled it corpus-wide) -- see
    test_upsert_never_overwrites_externally_owned_columns below.
    """
    set_columns = _upsert_set_columns()
    all_columns = _sql_column_names(FEATURE_VECTOR_UPSERT_SQL)
    expected = [c for c in all_columns if c not in _NEVER_UPDATED_COLUMNS]
    assert set_columns == expected
    assert len(set_columns) == len(set(set_columns)), "Duplicate column in DO UPDATE SET"


def test_upsert_never_overwrites_externally_owned_columns():
    """_EXTERNALLY_OWNED_COLUMNS must never appear in DO UPDATE SET.

    backfill_feature_factory.py and FeatureVectorWriter always pass
    regime=None (they don't compute regime -- regime_writer.py does, via a
    separate `UPDATE ... WHERE regime IS NULL` pass run afterward). If the
    refresh UPSERT's DO UPDATE SET included regime, every --refresh
    recompute would silently overwrite every already-labeled row's regime
    back to EXCLUDED's always-None value -- confirmed as exactly what
    happened corpus-wide (36.8M rows) on 2026-07-30. hmm_regime_prob/
    hmm_entropy/hmm_duration have the same exposure from a second writer
    (FeatureFactory's inline K=3 HMM computes the same field names) --
    confirmed live via an 11% same-model-invariant violation rate on
    SPY/1d rows carrying regime_writer's K=5 probability triple.
    """
    overlap = set(_upsert_set_columns()) & _EXTERNALLY_OWNED_COLUMNS
    assert not overlap, (
        f"DO UPDATE SET includes externally-owned column(s) {overlap} -- a "
        f"--refresh run will silently overwrite another writer's prior work"
    )


def test_psycopg2_variants_have_no_leftover_placeholders():
    assert "$" not in FEATURE_VECTOR_INSERT_SQL_PSYCOPG
    assert "$" not in FEATURE_VECTOR_UPSERT_SQL_PSYCOPG
    assert FEATURE_VECTOR_INSERT_SQL_PSYCOPG.count("%s") == len(
        set(_sql_column_names(FEATURE_VECTOR_INSERT_SQL))
    )
    assert FEATURE_VECTOR_UPSERT_SQL_PSYCOPG.count("%s") == len(
        set(_sql_column_names(FEATURE_VECTOR_UPSERT_SQL))
    )


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


def test_regime_writer_set_cols_is_the_canonical_tuple_not_a_copy():
    """services/regime_writer.py must import REGIME_WRITER_OWNED_COLUMN_NAMES
    from feature_vector_persistence.py rather than defining its own literal --
    the two ownership lists (this module's DO UPDATE SET exclusion and
    regime_writer's UPDATE set_cols) must be structurally the same object,
    not independently maintained copies that can silently drift apart."""
    import services.regime_writer as regime_writer_module

    assert regime_writer_module.REGIME_WRITER_OWNED_COLUMN_NAMES is REGIME_WRITER_OWNED_COLUMN_NAMES
