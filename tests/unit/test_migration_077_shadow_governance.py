"""Unit tests for migration 077_shadow_governance.sql — parse-based, no live DB."""
from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = Path("production/migrations/077_shadow_governance.sql")


def _sql() -> str:
    return MIGRATION_PATH.read_text()


def test_migration_file_exists():
    assert MIGRATION_PATH.exists(), "077_shadow_governance.sql must exist"


def test_shadow_registry_table_created():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS shadow_registry" in sql


def test_shadow_transition_log_table_created():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS shadow_transition_log" in sql


def test_shadow_registry_primary_key():
    sql = _sql()
    assert "component_name" in sql and "PRIMARY KEY" in sql


def test_shadow_registry_component_type_check():
    sql = _sql()
    assert "CHECK (component_type IN ('i7_plugin', 'swarm_agent'))" in sql


def test_shadow_registry_is_shadow_default_true():
    sql = _sql()
    assert "is_shadow" in sql and "DEFAULT TRUE" in sql


def test_shadow_registry_default_gate_params():
    """Verify D-02 defaults are present in DDL."""
    sql = _sql()
    assert "DEFAULT 100" in sql    # min_n
    assert "DEFAULT 0.0" in sql    # min_ev_r
    assert "DEFAULT 0.05" in sql   # ci_alpha
    assert "DEFAULT 30" in sql     # demotion_lookback_days
    assert "DEFAULT -0.05" in sql  # demotion_threshold_ev_r
    assert "DEFAULT 3" in sql      # demotion_min_evaluations


def test_shadow_transition_log_from_state_check():
    sql = _sql()
    assert "CHECK (from_state IN ('shadow', 'live'))" in sql


def test_shadow_transition_log_to_state_check():
    sql = _sql()
    assert "CHECK (to_state IN ('shadow', 'live'))" in sql


def test_shadow_transition_log_index():
    sql = _sql()
    assert "CREATE INDEX IF NOT EXISTS" in sql
    assert "shadow_transition_log" in sql
    assert "triggered_at DESC" in sql


def test_migration_idempotent_keywords():
    """Both tables and index use IF NOT EXISTS."""
    sql = _sql()
    assert sql.count("IF NOT EXISTS") >= 3
