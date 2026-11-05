"""CI guard: the rebuild writer, through bulk_load, is the only writer of feature_vectors (todo 590).

Since migration 570 `feature_vectors` is the kernel table: services/backfill_feature_factory.py
fills every column (regime columns included, in the same pass, R-10) through
services/_batch_utils.py bulk_load. The v1 in-place writers (regime_writer and the corpus repair
scripts) were deleted in todo 590. Three layers hold the invariant:

- a write statement on the table's literal name (the single-writer registry's `writer_pattern`:
  INSERT, UPDATE, DELETE, COPY, TRUNCATE, MERGE, asyncpg copy_*_to_table) fails here unless the
  allow-list below names the file with a reason;
- bulk_load composes the target through sql.Identifier, invisible to any grep, so BulkLoadSpec
  refuses any writer but the rebuild for this table at construction (SOLE_BULK_LOAD_WRITERS);
- no in-place write session can open on it (it left _WRITE_SESSION_HARDENED_TABLES at 570).

A write through a table name held in a variable (f"INSERT INTO {table}") is invisible to the scan,
as in every boundary test. Test directories are not scanned. CI-clean: filesystem only.
"""

from __future__ import annotations

import functools
from pathlib import Path

from services._batch_utils import _WRITE_SESSION_HARDENED_TABLES, SOLE_BULK_LOAD_WRITERS
from services.feature_vector_writer import _REQUIRED_COLUMNS
from src.intelligence.features.feature_vector_persistence import feature_vectors_columns
from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)
from tests.unit.test_single_writer_registry import writer_pattern

_REPO_ROOT = Path(__file__).parent.parent.parent  # tests/unit/ -> repo root
_SEARCH_DIRS = ("services", "src", "scripts")
_FILE_GLOBS = ("*.py", "*.sh", "*.sql")

_ALLOW_LIST: dict[str, str] = {
    "services/backfill_feature_factory.py": (
        "PERMANENT: the sole writer (through bulk_load); the hit is its kill-procedure comment "
        "that finds a leftover COPY backend."
    ),
    "src/intelligence/features/feature_vector_persistence.py": (
        "DORMANT: FEATURE_VECTOR_INSERT_SQL, the legacy v1 contract of the disabled "
        "indicagent-feature-vector-writer; it cannot write the kernel table (its startup schema "
        "check requires pipeline_version, pinned below), and reactivation needs the kernel row "
        "contract first (docs/operations/operations-infrastructure.md)."
    ),
}

_REMEDY = (
    "feature_vectors has one writer: services/backfill_feature_factory.py through bulk_load. "
    "Compute the column in the kernel registry instead, or add the file to the allow-list here "
    "with a real reason."
)


@functools.cache
def _hits() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, writer_pattern("feature_vectors"), _FILE_GLOBS
    )


def test_no_unlisted_feature_vectors_writers() -> None:
    assert_no_unlisted_references(
        _hits(), _ALLOW_LIST, what="feature_vectors writers", remedy=_REMEDY
    )


def test_feature_vectors_writer_allow_list_has_no_stale_entries() -> None:
    assert_allow_list_has_no_stale_entries(_hits(), _ALLOW_LIST)


def test_sole_writer_names_are_the_writers_own_constants() -> None:
    """A rename of a writer's job name must move the gate with it, or every spec the writer
    builds would be refused; the research reader matches the rebuild's name exactly too."""
    from services import backfill_feature_factory, ic_measure
    from src.intelligence.research.feature_inputs import REBUILD_WRITER

    assert SOLE_BULK_LOAD_WRITERS["feature_vectors"] == backfill_feature_factory._JOB
    assert SOLE_BULK_LOAD_WRITERS["feature_vectors"] == REBUILD_WRITER
    assert SOLE_BULK_LOAD_WRITERS["feature_ic_scores"] == f"{ic_measure._WRITER}."


def test_no_in_place_write_session_can_open_on_feature_vectors() -> None:
    assert "feature_vectors" not in _WRITE_SESSION_HARDENED_TABLES


def test_the_dormant_streaming_writer_refuses_the_kernel_table() -> None:
    """Its startup check requires a v1-only column the kernel table never has, so it refuses
    before any INSERT."""
    assert "pipeline_version" in _REQUIRED_COLUMNS
    assert "pipeline_version" not in feature_vectors_columns()
