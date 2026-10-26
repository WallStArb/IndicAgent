"""Source-level contract test for migration 515 (research attempt schema, phase 187 plan 01).

Reads the .sql file as text: no DB, CI-clean. Whole-line SQL comments are stripped before
matching so a header sentence cannot satisfy an assertion about the real DDL.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"(?m)^\s*--[^\n]*")


def _sql() -> str:
    return _SQL_LINE_COMMENT_RE.sub(
        "", read_source("production", "migrations", "515_research_attempt_schema.sql")
    )


def _between(sql: str, start: str, end: str) -> str:
    i = sql.index(start)
    return sql[i : sql.index(end, i)]


def test_one_transaction():
    sql = _sql().strip()
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")


def test_concept_recipe_columns_and_keys():
    body = _between(_sql(), "CREATE TABLE concept_recipe", ");\n")
    for column in (
        "concept_id        uuid        NOT NULL REFERENCES concept_registry (concept_id)",
        "recipe_hash       text        NOT NULL UNIQUE CHECK (recipe_hash ~ '^[0-9a-f]{64}$')",
        "code_commit       text        NOT NULL CHECK (code_commit ~ '^[0-9a-f]{40}$')",
        "params            jsonb",
        "apr_values        jsonb",
        "inputs            jsonb",
        "universe_selector jsonb",
        "cvr_codes         jsonb",
        "mechanism         text",
        "sources           text[]",
        "author            text        NOT NULL",
        "UNIQUE (concept_id, version)",
    ):
        assert column in body, column


def test_concept_recipe_is_append_only():
    sql = _sql()
    assert "BEFORE UPDATE OR DELETE ON concept_recipe" in sql
    assert "BEFORE TRUNCATE ON concept_recipe" in sql


def test_attempt_columns_and_widened_checks():
    sql = _sql()
    for column in (
        "ADD COLUMN recipe_hash          text REFERENCES concept_recipe (recipe_hash)",
        "ADD COLUMN informed_by          uuid REFERENCES research_run (run_id)",
        "ADD COLUMN decision_t",
        "ADD COLUMN n_sessions",
        "ADD COLUMN span_end",
    ):
        assert column in sql, column
    assert "CHECK (mode = ANY (ARRAY['real', 'exploration']))" in sql
    assert "ARRAY['evidence', 'book_test', 'pod_book', 'legacy_verdict']" in sql
    assert "CHECK (kind <> 'book_test' OR (budget_m IS NOT NULL" in sql


def test_guard_freezes_recipe_and_informed_by_and_starts_headlines_null():
    guard = _between(_sql(), "CREATE OR REPLACE FUNCTION fn_research_run_guard", "$$ LANGUAGE")
    assert "NEW.recipe_hash IS DISTINCT FROM OLD.recipe_hash" in guard
    assert "NEW.informed_by IS DISTINCT FROM OLD.informed_by" in guard
    assert "NEW.decision_t IS NOT NULL" in guard  # a started row carries no headline numbers


def test_series_table_is_insert_only_after_a_terminal_run():
    sql = _sql()
    body = _between(sql, "CREATE TABLE research_run_series", ");\n")
    assert "run_id     uuid        PRIMARY KEY REFERENCES research_run (run_id)" in body
    assert "cardinality(sessions) = cardinality(d_s)" in body
    guard = _between(sql, "FUNCTION fn_research_run_series_guard", "$$ LANGUAGE")
    assert "parent_status NOT IN ('completed', 'failed')" in guard
    assert "BEFORE INSERT OR UPDATE OR DELETE ON research_run_series" in sql
    assert "BEFORE TRUNCATE ON research_run_series" in sql


def test_every_ucr_fk_is_indexed():
    sql = _sql()
    for index in (
        "ON concept_registry (parent_concept_id)",
        "ON research_run (concept_id)",
        "ON research_run (informed_by)",
        "ON concept_recipe (concept_id)",
        "ON instrument_classification (scheme)",
    ):
        assert index in sql, index
