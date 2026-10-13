"""Source-level contract test for migration 477 (ohlcv_revision origin 'pending', plan 191-05).

Reads the .sql file as text: no DB, no network. Whole-line SQL comments are stripped first so a
header sentence cannot satisfy an assertion about the real DDL.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_NAME = "477_ohlcv_revision_origin_pending.sql"


def _sql() -> str:
    return re.sub(r"(?m)^\s*--[^\n]*", "", read_source("production", "migrations", _NAME))


def test_origin_check_admits_pending_next_to_the_existing_origins():
    sql = _sql()
    assert "DROP CONSTRAINT IF EXISTS ohlcv_revision_origin_check" in sql
    assert "CHECK (origin IN ('load', 'archive_segment', 'raw', 'pending'))" in sql


def test_migration_is_constraint_only_and_idempotent():
    sql = _sql()
    for forbidden in ("UPDATE ", "DELETE ", "INSERT ", "DROP TABLE", "ALTER COLUMN", "TRUNCATE"):
        assert forbidden not in sql
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
