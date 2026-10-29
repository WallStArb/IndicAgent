"""Migration 538 (phase 187 plan 14 Task 2), source level: the subset_refit kind, five typed headline
columns NULL at insert, the guard refusing them at insert, the APR keys seeded. No database."""

import re

from tests.unit._source_grep_helpers import read_source

_SQL = re.sub(
    r"--[^\n]*",
    "",
    read_source("production", "migrations", "538_contribution_headline_columns.sql"),
)
_COLUMNS = (
    "n_families",
    "effective_breadth",
    "top_group_share",
    "lofo_max_t_drop",
    "sign_stability_min",
)


def test_one_transaction_and_the_new_kind():
    assert _SQL.count("BEGIN;") == 1 and _SQL.count("COMMIT;") == 1
    assert "'subset_refit'" in _SQL and "DROP CONSTRAINT research_run_kind_check" in _SQL


def test_headline_columns_are_added_nullable():
    for column in _COLUMNS:
        assert re.search(
            rf"ADD COLUMN IF NOT EXISTS {column}\s+(integer|double precision)\s*[,;]", _SQL
        )


def test_guard_refuses_headline_numbers_at_insert():
    guard = _SQL[_SQL.index("CREATE OR REPLACE FUNCTION fn_research_run_guard") :]
    for column in _COLUMNS:
        assert f"NEW.{column} IS NOT NULL" in guard
    assert "a row must be inserted as started" in guard  # the rest of the guard is kept
    assert "already terminal" in guard


def test_apr_keys_are_seeded_in_all_three_tables():
    for key in ("shapley_exact_max_families", "shapley_samples", "shapley_seed", "cluster_corr"):
        assert _SQL.count(f"alpha.research.contribution.{key}") >= 2
    assert "INSERT INTO config_history" in _SQL and "INSERT INTO config_state" in _SQL


def test_exact_shapley_limit_migration_updates_schema_state_and_history():
    sql = re.sub(
        r"--[^\n]*",
        "",
        read_source("production", "migrations", "539_contribution_shapley_exact_limit_8.sql"),
    )
    assert "SET default_value = '8'" in sql and "config_value = '8'" in sql
    assert "INSERT INTO config_history" in sql and sql.count("BEGIN;") == 1
