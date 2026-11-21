"""Migration 606 contract: security_type is one append-only row per security and rule (no database)."""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_CODE = re.sub(r"--[^\n]*", "", read_source("production", "migrations", "606_security_type.sql"))
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_the_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;") and _CODE.rstrip().endswith("COMMIT;")


def test_one_row_per_security_and_rule_over_a_real_instrument():
    assert "PRIMARY KEY (symbol, rule_id)" in _FLAT
    assert "symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT" in _FLAT
    for column in ("class_conflict boolean NOT NULL", "evidence jsonb NOT NULL"):
        assert column in _FLAT
    assert "security_type text NOT NULL CHECK (security_type <> '')" in _FLAT


def test_the_table_refuses_update_delete_and_truncate():
    assert "BEFORE UPDATE OR DELETE ON security_type " in _FLAT
    assert "BEFORE TRUNCATE ON security_type " in _FLAT


def test_it_is_a_plain_table_so_no_compressed_column_change_and_no_vacuum_clause():
    assert "ALTER COLUMN" not in _FLAT and "create_hypertable" not in _FLAT
