"""Source-level contract test for migration 380 (D1 raw observation store, phase 185
plan 02).

Asserts every required clause is present in the migration text, per the plan's task 1.
Reads the .sql file as text -- no DB, no network, CI-clean, mirroring
test_earnings_season_migration_contract.py's shape.

SQL comment lines are stripped before matching so a header sentence that merely
mentions a clause cannot satisfy the assertion that the real DDL contains it.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")

_APR_KEYS = (
    "infra.bar_campaign.client_ids",
    "infra.ibkr_history_lease.nightly_wait_minutes",
    "infra.ibkr_history_lease.priority_wait_minutes",
    "infra.ohlcv_observation.copy_batch_rows",
)


def _migration_text_no_comments() -> str:
    raw = read_source("production", "migrations", "380_ohlcv_observation_store.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def test_creates_both_d1_tables():
    sql = _migration_text_no_comments()
    assert "CREATE TABLE IF NOT EXISTS ohlcv_request" in sql
    assert "CREATE TABLE IF NOT EXISTS ohlcv_observation" in sql


def test_observation_table_is_1d_only():
    sql = _migration_text_no_comments()
    assert "CHECK (timeframe = '1d')" in sql


def test_source_column_is_checked_to_ibkr():
    sql = _migration_text_no_comments()
    assert "CHECK (source IN ('ibkr'))" in sql


def test_prices_carry_explicit_finite_check():
    sql = _migration_text_no_comments()
    assert "CONSTRAINT ohlcv_observation_finite CHECK" in sql
    for col in ("open", "high", "low", "close"):
        assert f"{col} <> 'NaN'" in sql
        assert f"{col} <> 'Infinity'" in sql
        assert f"{col} <> '-Infinity'" in sql


def test_both_tables_have_row_and_truncate_triggers():
    sql = _migration_text_no_comments()
    for table in ("ohlcv_request", "ohlcv_observation"):
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql, f"row trigger missing on {table}"
        assert f"BEFORE TRUNCATE ON {table}" in sql, f"truncate trigger missing on {table}"
        assert f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}" in sql
        assert f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}" in sql


def test_append_only_function_raises_with_table_and_op():
    sql = _migration_text_no_comments()
    assert "CREATE OR REPLACE FUNCTION ohlcv_d1_append_only()" in sql
    assert "'% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP" in sql


def test_both_roles_exist_nologin():
    sql = _migration_text_no_comments()
    assert "CREATE ROLE ohlcv_observation_writer NOLOGIN" in sql
    assert "CREATE ROLE bar_derivation_writer NOLOGIN" in sql


def test_no_update_or_delete_granted_to_anyone():
    sql = _migration_text_no_comments()
    assert not re.search(
        r"GRANT[^;]*?\b(UPDATE|DELETE)\b", sql, re.IGNORECASE
    ), "D1 grants must be INSERT/SELECT only; UPDATE or DELETE must never be granted"


def test_public_revoked_of_rewrite_privileges():
    sql = _migration_text_no_comments()
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON ohlcv_request, ohlcv_observation FROM PUBLIC" in sql


def test_venue_head_view_exists():
    sql = _migration_text_no_comments()
    assert "CREATE OR REPLACE VIEW ohlcv_venue_head" in sql
    # The view must exclude SMART and LEGACY_IMPORT routes and read TRADES only.
    assert "o.route <> 'SMART'" in sql
    assert "o.route <> 'LEGACY_IMPORT'" in sql
    assert "o.what_to_show = 'TRADES'" in sql


def test_every_apr_key_appears_in_schema_state_and_history():
    sql = _migration_text_no_comments()
    for key in _APR_KEYS:
        assert sql.count(key) >= 3, (
            f"{key} must appear in config_schema, config_state, and config_history "
            f"(found {sql.count(key)} occurrences)"
        )


def test_apr_history_rows_cite_migration_380():
    sql = _migration_text_no_comments()
    assert sql.count("'migration_380'") >= len(_APR_KEYS)
