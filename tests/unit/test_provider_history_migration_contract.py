"""Source-level contract tests for migrations 464 and 465 (phase 190 plan 02, two-tier ledger).

Reads the .sql files as text: no DB, no network, CI-clean, in the pattern of
test_ohlcv_coverage_migration_contract.py. SQL line comments are stripped before DDL
assertions so header prose cannot satisfy an assertion about the real DDL. The one
header-level assertion (465's cutover-window application declaration) reads the raw text,
because that declaration IS the header's payload.

These tests are source-level and MUST NOT depend on live apply timing: they pass through
waves 1-4 while 465 is committed but un-applied. Any DB-backed migration assertion belongs to
tests/integration/test_ohlcv_coverage_atomic_write.py, inside a transaction-rollback fixture.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"(?m)^\s*--[^\n]*")


def _sql_464() -> str:
    raw = read_source("production", "migrations", "464_ohlcv_coverage_provider_dimension.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def _sql_465() -> str:
    raw = read_source("production", "migrations", "465_provider_history_two_tier_keys.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def _raw_465() -> str:
    return read_source("production", "migrations", "465_provider_history_two_tier_keys.sql")


# ---------------------------------------------------------------------------
# Migration 464: additive provider columns
# ---------------------------------------------------------------------------


def test_464_adds_the_provider_column_with_its_check():
    sql = _sql_464()
    assert "ALTER TABLE ohlcv_coverage ADD COLUMN provider text NOT NULL DEFAULT 'ibkr'" in sql
    assert "ohlcv_coverage_provider_check" in sql
    assert "CHECK (provider <> '')" in sql


def test_464_adds_the_nullable_timeframe_column_to_provider_head():
    sql = _sql_464()
    assert "ALTER TABLE ohlcv_provider_head ADD COLUMN timeframe text;" in sql


def test_464_changes_no_key_and_drops_nothing():
    sql = _sql_464()
    assert not re.search(r"\bDROP\b", sql)
    assert not re.search(r"\bPRIMARY KEY\b", sql)
    # The only new constraint is the named provider CHECK, never a key or a table.
    constraints = re.findall(r"ADD CONSTRAINT (\w+)", sql)
    assert constraints == ["ohlcv_coverage_provider_check"], constraints
    assert not re.search(r"(?i)\bCREATE\s+TABLE\b", sql)


def test_464_has_no_new_apr_keys():
    sql = _sql_464()
    assert "config_schema" not in sql
    assert "config_state" not in sql
    assert "config_history" not in sql


def test_464_comments_state_the_stored_state_labeling_rule():
    raw = read_source("production", "migrations", "464_ohlcv_coverage_provider_dimension.sql")
    assert "COMMENT ON COLUMN ohlcv_coverage.provider" in _sql_464()
    assert "COMMENT ON COLUMN ohlcv_provider_head.timeframe" in _sql_464()
    # The labeling rule itself lives in the header and the COMMENTs (comment text survives
    # stripping only inside the COMMENT statements; the header prose is checked on the raw).
    assert "stored-state" in raw
    assert "ohlcv_load.source" in raw


# ---------------------------------------------------------------------------
# Migration 465: the breaking two-tier keys (committed un-applied until the cutover)
# ---------------------------------------------------------------------------


def test_465_header_declares_cutover_window_application():
    raw = _raw_465()
    assert "CUTOVER-WINDOW MIGRATION" in raw
    assert "190-06" in raw
    assert "STOPPED" in raw
    assert "42P10" in raw


def test_465_rekeys_provider_head_to_the_per_tf_pk():
    sql = _sql_465()
    assert "PRIMARY KEY (symbol, provider, timeframe)" in sql
    assert "ALTER COLUMN timeframe SET NOT NULL" in sql
    assert "UPDATE ohlcv_provider_head SET timeframe = '1d' WHERE timeframe IS NULL" in sql


def test_465_rekeys_coverage_to_include_provider():
    sql = _sql_465()
    assert "PRIMARY KEY (symbol, timeframe, provider)" in sql
    assert "ALTER TABLE ohlcv_coverage DROP CONSTRAINT ohlcv_coverage_pkey" in sql
    assert "ALTER TABLE ohlcv_provider_head DROP CONSTRAINT ohlcv_provider_head_pkey" in sql


def test_465_seeds_the_measured_floors_with_do_nothing():
    sql = _sql_465()
    raw = _raw_465()
    assert "'2006-07-01T22:00:00Z'" in sql
    assert "'2000-01-03'" in sql
    assert "ON CONFLICT (symbol, provider, timeframe) DO NOTHING" in sql
    assert "[measured]" in raw  # provenance stated ([measured], todo 526)
    assert "todo 526" in raw


def test_465_grant_excludes_delete_and_truncate():
    sql = _sql_465()
    grants = re.findall(r"GRANT[^;]*ohlcv_coverage[^;]*;", sql)
    assert len(grants) == 1, grants
    assert "GRANT SELECT, INSERT, UPDATE ON ohlcv_coverage TO bar_derivation_writer" in grants[0]
    assert "DELETE" not in grants[0]
    assert "TRUNCATE" not in grants[0]
    assert "ohlcv_observation_writer" not in sql


def test_465_drops_no_table_and_creates_no_hypertable():
    sql = _sql_465()
    assert not re.search(r"(?i)\bDROP\s+TABLE\b", sql)
    assert "create_hypertable" not in sql
