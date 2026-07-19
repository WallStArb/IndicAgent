"""Unit tests: migration 207 (alpha_frames.target_r_multiple + bootstrap seed) DDL assertions.

No DB. Reads the migration SQL text and asserts structural properties (code-review CR-02/WR-01).
"""

from __future__ import annotations

from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "production"
    / "migrations"
    / "207_alpha_frames_target_r_multiple.sql"
)


def _read_migration() -> str:
    return _MIGRATION_PATH.read_text()


def test_migration_207_file_exists():
    assert _MIGRATION_PATH.exists()


def test_adds_target_r_multiple_column():
    sql = _read_migration()
    assert "ADD COLUMN IF NOT EXISTS target_r_multiple double precision" in sql


def test_is_idempotent():
    sql = _read_migration()
    assert "IF NOT EXISTS" in sql
    assert "ON CONFLICT" in sql


def test_seeds_bootstrap_random_state_apr_key():
    sql = _read_migration()
    assert "alpha.scoring.bootstrap_random_state" in sql
    assert "config_schema" in sql
    assert "config_state" in sql
