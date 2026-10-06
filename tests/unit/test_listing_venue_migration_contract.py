"""Source-level contract test for migration 408 (listing_venue, phase 185 plan 24, D-25).

Reads the .sql text only (no DB), SQL line comments stripped first, mirroring
test_corporate_action_migration_contract.py.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_FILE = "408_listing_venue.sql"


def _raw() -> str:
    return read_source("production", "migrations", _FILE)


def _sql() -> str:
    return _SQL_LINE_COMMENT_RE.sub("", _raw())


def test_creates_table_with_required_columns():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS listing_venue" in sql
    assert "symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT" in sql
    assert "venue text NOT NULL" in sql
    assert "valid_from date NOT NULL" in sql
    assert "valid_to date NULL" in sql
    assert "evidence jsonb NOT NULL" in sql
    assert "batch_id uuid REFERENCES bar_derivation_batch(batch_id)" in sql
    assert "recorded_at timestamptz NOT NULL DEFAULT now()" in sql
    assert "CHECK (valid_to IS NULL OR valid_to > valid_from)" in sql


def test_spans_never_overlap_per_symbol():
    sql = _sql()
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in sql
    assert "EXCLUDE USING gist" in sql
    assert "symbol WITH =" in sql
    assert "daterange(valid_from, valid_to, '[)') WITH &&" in sql


def test_append_only_except_closing_valid_to():
    sql = _sql()
    assert "BEFORE INSERT OR UPDATE OR DELETE ON listing_venue" in sql
    assert "BEFORE TRUNCATE ON listing_venue" in sql
    assert "OLD.valid_to IS NOT NULL" in sql
    assert "NEW.valid_to IS NULL" in sql
    assert "DROP TRIGGER IF EXISTS trg_listing_venue_append_only ON listing_venue" in sql
    assert "DROP TRIGGER IF EXISTS trg_listing_venue_no_truncate ON listing_venue" in sql


def test_header_states_why_historical_valid_from_is_allowed():
    header = _raw().split("BEGIN;")[0].lower()
    assert "reconstructed" in header
    assert "valid_from" in header


def test_writer_role_grants():
    sql = _sql()
    assert "GRANT INSERT, SELECT ON listing_venue TO bar_derivation_writer" in sql
    assert "GRANT UPDATE (valid_to) ON listing_venue TO bar_derivation_writer" in sql
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON listing_venue FROM PUBLIC" in sql
