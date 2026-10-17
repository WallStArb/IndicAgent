"""Source-level contract test for the migration that drops the two old bar stores
(phase 191 plan 16, design doc step 8).

The object names below are the live verified list (re-checked against pg_trigger,
pg_constraint and pg_depend on 2026-10-17), not anything parsed from migration 380's text:

- triggers: only the archive's no_delete and no_truncate exist (ohlcv_observation has had
  no append-only triggers since migration 438; dropping what is not there is refused here);
- trigger functions: ohlcv_archive_no_delete serves only the archive's triggers;
  bar_derivation_append_only is shared with bar_content_digest and must stay;
- foreign keys: ohlcv_observation_request_id_fkey lives on the observation (references
  ohlcv_request) and ohlcv_intraday_raw_archive_batch_id_fkey lives on the archive
  (references bar_derivation_batch); both go with their tables, no explicit drop;
- grants to ohlcv_observation_writer and bar_derivation_writer go with the tables.

SQL line comments are stripped before matching, so a header sentence cannot satisfy a
clause assertion. The migration file is located by name glob, never by number.
"""

from __future__ import annotations

import re

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")

_MIGRATION_GLOB = "*_drop_observation_and_raw_archive.sql"

_ARCHIVE_ONLY_FUNCTION = "ohlcv_archive_no_delete"
_SHARED_FUNCTION = "bar_derivation_append_only"
_TRIGGERS = (
    "trg_ohlcv_intraday_raw_archive_no_delete",
    "trg_ohlcv_intraday_raw_archive_no_truncate",
)
_FK_NAMES = (
    "ohlcv_observation_request_id_fkey",
    "ohlcv_intraday_raw_archive_batch_id_fkey",
)
_RETIRED_KEYS = (
    "infra.backfill.ohlcv_insert_batch_size",
    "infra.raw_backfill.statement_timeout_s",
)


def _migration_text_no_comments() -> str:
    import pathlib

    from tests.unit._migration_catalog import MIGRATIONS_DIR

    matches = sorted(pathlib.Path(MIGRATIONS_DIR).glob(_MIGRATION_GLOB))
    assert len(matches) == 1, f"expected exactly one {_MIGRATION_GLOB}, found {matches}"
    return _SQL_LINE_COMMENT_RE.sub("", matches[0].read_text())


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_is_one_transaction_with_a_lock_timeout():
    sql = _flat(_migration_text_no_comments())
    assert sql.strip().startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;")
    assert "SET LOCAL lock_timeout" in sql


def test_guard_raises_on_unexpected_pg_depend_dependents():
    sql = _migration_text_no_comments()
    assert "pg_depend" in sql
    assert "RAISE EXCEPTION" in sql


def test_drops_both_archive_triggers_before_the_tables():
    sql = _flat(_migration_text_no_comments())
    table_drop = sql.index("DROP TABLE ohlcv_intraday_raw_archive;")
    for trigger in _TRIGGERS:
        trigger_drop = sql.index(f"DROP TRIGGER IF EXISTS {trigger} ON ohlcv_intraday_raw_archive;")
        assert trigger_drop < table_drop, f"{trigger} must be dropped before the table"


def test_drops_the_archive_table_before_the_observation():
    sql = _flat(_migration_text_no_comments())
    assert sql.index("DROP TABLE ohlcv_intraday_raw_archive;") < sql.index(
        "DROP TABLE ohlcv_observation;"
    )


def test_drops_the_archive_only_function_after_both_tables():
    # The archive's ~90 chunk-level trigger clones reference the function too, and they
    # only disappear with the table, so the function drop must follow the table drops.
    sql = _flat(_migration_text_no_comments())
    fn_drop = sql.index(f"DROP FUNCTION IF EXISTS {_ARCHIVE_ONLY_FUNCTION}()")
    assert fn_drop > sql.index("DROP TABLE ohlcv_intraday_raw_archive;")
    assert fn_drop > sql.index("DROP TABLE ohlcv_observation;")


def test_keeps_the_shared_append_only_function():
    sql = _migration_text_no_comments()
    assert _SHARED_FUNCTION not in sql, "bar_derivation_append_only serves bar_content_digest"


def test_foreign_keys_go_with_their_tables_no_explicit_drop():
    sql = _migration_text_no_comments()
    for fk in _FK_NAMES:
        assert fk not in sql, f"{fk} drops with its own table; no explicit drop statement"


def test_no_cascade_and_no_chunk_round_trip():
    sql = _migration_text_no_comments()
    assert not re.search(r"CASCADE|decompress_chunk|compress_chunk", sql, re.IGNORECASE)


def test_ohlcv_request_is_never_named_as_a_drop_target():
    sql = _migration_text_no_comments()
    assert "ohlcv_request" not in sql


def test_bar_derivation_batch_is_not_dropped():
    sql = _migration_text_no_comments()
    assert "DROP TABLE bar_derivation_batch" not in sql


def test_retires_the_two_orphaned_apr_keys_with_history():
    sql = _migration_text_no_comments()
    for key in _RETIRED_KEYS:
        assert key in sql, f"{key} must be retired by this migration"
    for table in ("config_history", "config_state", "config_schema"):
        assert f"DELETE FROM {table}" in sql, f"the retirement order deletes {table}"
    # the plan citation is prose in the migration header, so this clause reads the raw text
    assert "191-16" in _migration_text(), "the retirement must cite plan 191-16"


def _migration_text() -> str:
    import pathlib

    from tests.unit._migration_catalog import MIGRATIONS_DIR

    matches = sorted(pathlib.Path(MIGRATIONS_DIR).glob(_MIGRATION_GLOB))
    assert len(matches) == 1, f"expected exactly one {_MIGRATION_GLOB}, found {matches}"
    return matches[0].read_text()
