"""Source-level contract test for migration 432 (ohlcv_coverage, phase 189 plan 01, CD-03).

Reads the .sql file as text: no DB, no network, CI-clean, mirroring
test_ohlcv_observation_migration_contract.py. SQL line comments are stripped before matching
so a header sentence that mentions a clause cannot satisfy an assertion about the real DDL.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

# Whole-line comments only: a description string legitimately contains "--reset-failures".
_SQL_LINE_COMMENT_RE = re.compile(r"(?m)^\s*--[^\n]*")
_PROVENANCE_RE = re.compile(r"\[(initial_estimate|user_preference|conventional)\]")

_APR_KEYS = (
    "infra.ibkr.inter_item_pause_s",
    "infra.ibkr.history_request_timeout",
    "infra.ibkr.history_request_retries",
    "infra.backfill.max_consecutive_failures",
    "infra.backfill.max_staleness_days_before_preempt",
    "infra.backfill.priority_tf_order",
    "infra.backfill.default_scopes",
    "infra.backfill.run_budget_minutes",
)


def _sql() -> str:
    raw = read_source("production", "migrations", "432_ohlcv_coverage.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def test_creates_the_ledger_with_its_primary_key():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS ohlcv_coverage" in sql
    assert "PRIMARY KEY (symbol, timeframe)" in sql


def test_all_four_check_constraints():
    sql = _sql()
    assert "last_fetch_status IS NULL OR last_fetch_status IN ('ok', 'no_data', 'error')" in sql
    assert "CHECK (consecutive_failures >= 0)" in sql
    assert "CHECK (row_count >= 0)" in sql
    assert "earliest_timestamp <= latest_timestamp" in sql


def test_grant_is_select_insert_update_to_the_bar_writer_only():
    sql = _sql()
    assert "GRANT SELECT, INSERT, UPDATE ON ohlcv_coverage TO bar_derivation_writer" in sql
    grants = re.findall(r"GRANT[^;]*ohlcv_coverage[^;]*;", sql)
    assert len(grants) == 1, grants
    assert "DELETE" not in grants[0]
    assert "TRUNCATE" not in grants[0]
    assert "ohlcv_observation_writer" not in sql


def _schema_description(sql: str, key: str) -> str:
    # The description is the last field of the row: a quoted string closing at end of line.
    match = re.search(rf"'{re.escape(key)}',\s*'\w+',\s*'[^\n]*',\s*[^\n]*,\s*'(\[[^\n]*)'\n", sql)
    assert match, f"config_schema row for {key} not found"
    return match.group(1)


def test_every_apr_key_is_seeded_with_provenance_in_all_three_tables():
    sql = _sql()
    for key in _APR_KEYS:
        assert sql.count(f"'{key}'") >= 3, f"{key} not in config_schema/state/history"
        description = _schema_description(sql, key)
        assert _PROVENANCE_RE.search(description), f"{key} description lacks a provenance tag"
        assert "Not an ML learning target" in description
    assert "'migration_432'" in sql


def test_bootstrap_reads_the_three_stored_state_sources():
    sql = _sql()
    assert "INSERT INTO ohlcv_coverage" in sql
    for source in ("ohlcv_intraday_raw_archive", "market_data_ohlcv_tradeable", "ohlcv_request"):
        assert f"FROM {source}" in sql, source
    assert "ON CONFLICT (symbol, timeframe) DO NOTHING" in sql


def test_migration_is_additive_and_not_a_hypertable():
    sql = _sql()
    assert not re.search(r"(?i)\bDROP\s+[A-Z]", sql)
    assert "create_hypertable" not in sql
