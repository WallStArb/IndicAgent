"""Source-level contract test for migration 400 (corporate_action, phase 185 plan 15).

Reads the .sql text only (no DB), SQL line comments stripped first, mirroring
test_ohlcv_observation_migration_contract.py.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")

_APR_KEYS = (
    "threshold.seam.rel_tol",
    "threshold.seam.min_run",
    "threshold.seam.ratio_snap_tol",
    "infra.bar_campaign.bootstrap_years",
)


def _sql() -> str:
    raw = read_source("production", "migrations", "400_corporate_action.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def test_creates_table_with_required_columns_and_checks():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS corporate_action" in sql
    assert "REFERENCES instruments(symbol) ON DELETE RESTRICT" in sql
    assert "CHECK (action_type IN ('split', 'reverse_split'))" in sql
    assert "CHECK (factor > 0 AND factor <> 'Infinity' AND factor <> 'NaN')" in sql
    assert "CHECK (inferred_by IN ('seam_audit', 'nightly_overlap'))" in sql
    assert "evidence_request_ids uuid[] NOT NULL" in sql
    assert "supersedes uuid NULL REFERENCES corporate_action(action_id)" in sql
    assert "batch_id uuid REFERENCES bar_derivation_batch(batch_id)" in sql


def test_append_only_triggers_cover_update_delete_and_truncate():
    sql = _sql()
    assert "BEFORE UPDATE OR DELETE ON corporate_action" in sql
    assert "BEFORE TRUNCATE ON corporate_action" in sql
    assert "DROP TRIGGER IF EXISTS trg_corporate_action_append_only ON corporate_action" in sql
    assert "DROP TRIGGER IF EXISTS trg_corporate_action_no_truncate ON corporate_action" in sql
    assert "'% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP" in sql


def test_current_view_excludes_superseded_rows():
    sql = _sql()
    assert "CREATE OR REPLACE VIEW corporate_action_current" in sql
    assert "newer.supersedes = ca.action_id" in sql


def test_writer_role_grants_are_insert_and_select_only():
    sql = _sql()
    assert "GRANT INSERT, SELECT ON corporate_action TO bar_derivation_writer" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON corporate_action FROM PUBLIC" in sql


def test_seeds_every_apr_key_in_schema_state_and_history():
    sql = _sql()
    for key in _APR_KEYS:
        assert sql.count(f"'{key}'") == 3, f"{key} must appear in schema, state and history"
