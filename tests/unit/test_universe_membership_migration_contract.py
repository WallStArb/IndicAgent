"""Migration 597 contract: universe_membership tables are append-only with a build ledger."""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_CODE = re.sub(
    r"--[^\n]*", "", read_source("production", "migrations", "597_universe_membership.sql")
)
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_universe_membership_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;") and _CODE.rstrip().endswith("COMMIT;")


def test_member_rows_reference_the_ledger_and_instruments():
    assert "as_of date NOT NULL REFERENCES universe_membership_build(as_of)" in _FLAT
    assert "REFERENCES instruments(symbol)" in _FLAT
    assert "PRIMARY KEY (as_of, symbol)" in _FLAT


def test_both_tables_refuse_update_delete_and_truncate():
    for table in ("universe_membership", "universe_membership_build"):
        assert f"BEFORE UPDATE OR DELETE ON {table} " in _FLAT
        assert f"BEFORE TRUNCATE ON {table} " in _FLAT
