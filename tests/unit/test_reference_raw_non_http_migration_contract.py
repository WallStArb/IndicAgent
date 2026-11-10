"""Source-level contract test for migration 587 (reference_raw holds non-HTTP answers).

Reads the .sql text only. The behaviour (an ibkr:// row with a NULL status inserts, an https
row without one and an ibkr:// row with one are refused) was exercised against the live
database inside a rolled-back transaction when the migration was written.
"""

from __future__ import annotations

from tests.unit._migration_catalog import strip_sql_comments
from tests.unit._source_grep_helpers import read_source


def _sql() -> str:
    return strip_sql_comments(
        read_source("production", "migrations", "587_reference_raw_non_http_answers.sql")
    )


def test_one_transaction_touching_only_reference_raw_http_status():
    sql = _sql().strip()
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")
    assert "ALTER TABLE reference_raw ALTER COLUMN http_status DROP NOT NULL;" in sql
    assert "VACUUM" not in sql and "DROP TABLE" not in sql


def test_status_present_exactly_for_http_answers():
    sql = " ".join(_sql().split())
    assert "CHECK ((http_status IS NOT NULL) = (url ~ '^https?://'))" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_reference_raw_http_status_iff_http" in sql
