"""Source-level contract test for migration 350 (earnings-season calendar primitive).

Asserts every required clause is present in the migration text, per 176-02-PLAN.md's
<behavior> block. Reads the .sql file as text -- no DB, no network, CI-clean, mirroring
test_compressed_hypertable_migration_vacuum_check.py's shape.

SQL comment lines are stripped before counting so a header sentence that merely mentions
a clause (e.g. this migration's own header explaining why 'broadcast', true is mandatory)
cannot satisfy the assertion that the real INSERT contains it.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _migration_text_no_comments() -> str:
    raw = read_source("production", "migrations", "350_earnings_season_calendar_primitive.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def test_adds_both_new_columns():
    sql = _migration_text_no_comments()
    assert "ADD COLUMN IF NOT EXISTS earnings_season_flag" in sql
    assert "ADD COLUMN IF NOT EXISTS days_since_quarter_end" in sql


def test_both_concept_registry_rows_carry_broadcast_and_tier():
    sql = _migration_text_no_comments()
    # Both metadata objects must declare broadcast=true and tier=1_interaction.
    assert sql.count("'broadcast', true") == 2
    assert sql.count("'1_interaction'") >= 2


def test_both_concept_registry_rows_declare_quarter_position_parent():
    sql = _migration_text_no_comments()
    parent_arrays = re.findall(r"parent_features',\s*jsonb_build_array\(([^)]*)\)", sql)
    assert (
        len(parent_arrays) == 2
    ), f"expected exactly 2 parent_features arrays, found {len(parent_arrays)}"
    for array_body in parent_arrays:
        assert array_body.strip(), "parent_features array must be non-empty"
        assert "quarter_position" in array_body


def test_regime_scope_check_widened_to_all_four_scopes():
    sql = _migration_text_no_comments()
    match = re.search(
        r"ADD CONSTRAINT feature_ic_scores_regime_scope_chk\s*"
        r"CHECK \(regime_scope IN \(([^)]*)\)\)",
        sql,
    )
    assert match, "widened CHECK constraint not found"
    scopes = match.group(1)
    for expected in ("cross_sectional", "symbol_hmm", "pooled", "earnings_season"):
        assert f"'{expected}'" in scopes


def test_all_three_apr_keys_appear_in_schema_state_and_history():
    sql = _migration_text_no_comments()
    for key in (
        "feature.earnings_season.start_days",
        "feature.earnings_season.end_days",
        "alpha.ic.earnings_season_conditioned",
    ):
        assert sql.count(key) >= 3, (
            f"{key} must appear in config_schema, config_state, and config_history "
            f"(found {sql.count(key)} occurrences)"
        )


def test_no_alter_column_type_present():
    """No ALTER COLUMN ... TYPE means the compressed-hypertable VACUUM rule (CLAUDE.md)
    does not apply to this migration -- plain ADD COLUMN only."""
    sql = _migration_text_no_comments()
    assert not re.search(r"ALTER\s+COLUMN\s+\w+\s+TYPE", sql, re.IGNORECASE)


def test_concept_gate_seed_present_for_both_features():
    sql = _migration_text_no_comments()
    assert "INSERT INTO concept_gate" in sql
    assert "earnings_season_flag" in sql
    assert "days_since_quarter_end" in sql
