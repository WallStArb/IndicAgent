"""Source-level contract test for migration 478 (provider head kind, plan 191-06 review fixes).

Reads the .sql file as text: no DB, no network. Whole-line SQL comments are stripped first so a
header sentence cannot satisfy an assertion about the real DDL.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_NAME = "478_provider_head_kind_floor.sql"


def _sql() -> str:
    return re.sub(r"(?m)^\s*--[^\n]*", "", read_source("production", "migrations", _NAME))


def test_head_kind_separates_verified_heads_from_seeded_floors():
    sql = _sql()
    assert "ADD COLUMN IF NOT EXISTS head_kind text NOT NULL DEFAULT 'verified'" in sql
    assert "CHECK (head_kind IN ('verified', 'floor'))" in sql


def test_only_the_465_seed_rows_become_floors():
    sql = _sql()
    assert "SET head_kind = 'floor'" in sql
    assert "2006-07-01 22:00:00+00" in sql and "2000-01-03 00:00:00+00" in sql
    assert "verified_at >=" in sql and "verified_at <" in sql


def test_repair_resets_only_series_with_failures_before_their_own_first_bar():
    sql = _sql()
    assert "SET consecutive_failures = 0" in sql
    assert "r.outcome IN ('failed', 'timeout')" in sql
    assert "r.window_end <=" in sql and "m.vendor = 'ibkr'" in sql
    assert "infra.backfill.max_consecutive_failures" in sql


def test_no_raw_or_revision_ddl_and_one_transaction():
    sql = _sql()
    for table in ("ohlcv_raw", "ohlcv_revision"):
        assert f"ALTER TABLE {table}" not in sql
    assert "DELETE " not in sql and "DROP TABLE" not in sql and "TRUNCATE" not in sql
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
