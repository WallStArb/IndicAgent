"""Source-level contract test for migration 586 (Massive admission step 1 schema, todo 600).

Reads the .sql text only (no DB), SQL line comments stripped first, mirroring
test_listing_venue_migration_contract.py. The behaviour (triggers, exclusion constraints, the
foreign keys) was exercised against the live database inside a rolled-back transaction when the
migration was written; this file pins the text that behaviour rests on.
"""

from __future__ import annotations

import re

from tests.unit._migration_catalog import catalog, migration_files, strip_sql_comments
from tests.unit._source_grep_helpers import read_source

_FILE = "586_massive_admission_schema.sql"
_RETIRE_ONLY_TABLES = ("security_identifier", "ticker_event", "definition_epoch")


def _sql() -> str:
    return strip_sql_comments(read_source("production", "migrations", _FILE))


def _inferred_by_codes(sql: str) -> list[str]:
    match = re.search(
        r"ADD CONSTRAINT corporate_action_inferred_by_check\s+CHECK \(inferred_by IN \(([^)]*)\)\)",
        sql,
    )
    assert match, "the inferred_by CHECK is re-added"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def test_one_transaction():
    sql = _sql().strip()
    assert sql.startswith("BEGIN;") and sql.endswith("COMMIT;")


def test_cvr_codes_vendor_and_three_kinds():
    sql = _sql()
    for namespace, code in (
        ("bar_vendor", "massive"),
        ("bar_kind", "sip_flat_agg"),
        ("bar_kind", "sip_flat"),
        ("bar_kind", "sip_flat_adj"),
    ):
        assert f"('{namespace}', '{code}'" in sql
    assert "ON CONFLICT (namespace, code) DO NOTHING" in sql


def test_inferred_by_widens_the_previous_check_by_massive_reference_only():
    previous = _inferred_by_codes(
        strip_sql_comments(
            read_source("production", "migrations", "567_corporate_action_calendar_audit.sql")
        )
    )
    assert _inferred_by_codes(_sql()) == [*previous, "massive_reference"]


def test_creates_exactly_the_four_tables_and_seeds_no_apr_key():
    tables, keys = catalog([path for path in migration_files() if path.name == _FILE])
    assert tables == {"reference_raw", "security_identifier", "ticker_event", "definition_epoch"}
    assert keys == set()


def test_reference_raw_is_insert_only_with_manifest_lineage():
    sql = _sql()
    for column in (
        "body jsonb NOT NULL",
        "served_at timestamptz NOT NULL",
        "manifest_path text NOT NULL",
        "manifest_line integer NOT NULL",
        "file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$')",
        "as_of date NULL",
    ):
        assert column in sql
    assert "UNIQUE (manifest_path, manifest_line)" in sql
    assert "UNIQUE (vendor, endpoint, request_key, page, manifest_path)" in sql
    assert "BEFORE UPDATE OR DELETE ON reference_raw" in sql
    assert "BEFORE TRUNCATE ON reference_raw" in sql
    assert "CREATE OR REPLACE VIEW reference_raw_current" in sql


def test_retire_only_tables_share_one_guard_and_a_current_view():
    sql = _sql()
    for table in _RETIRE_ONLY_TABLES:
        assert f"BEFORE INSERT OR UPDATE OR DELETE ON {table}" in sql
        assert f"BEFORE TRUNCATE ON {table}" in sql
        assert f"CREATE OR REPLACE VIEW {table}_current" in sql
    assert sql.count("EXECUTE FUNCTION retire_once_append_only()") == 2 * len(_RETIRE_ONLY_TABLES)
    assert sql.count("CHECK ((retired_at IS NULL) = (retired_reason IS NULL))") == 3
    assert "(to_jsonb(NEW) - 'retired_at' - 'retired_reason')" in sql
    assert "NEW.retired_at := now();" in sql


def test_identity_overlap_rules_hold_among_unretired_rows():
    sql = _sql()
    for constraint, keys in (
        ("ex_security_identifier_one_value", "symbol WITH =, scheme WITH ="),
        ("ex_security_identifier_one_security", "scheme WITH =, value WITH ="),
        ("ex_ticker_event_one_security", "vendor WITH =, ticker WITH ="),
        ("ex_ticker_event_one_ticker", "vendor WITH =, symbol WITH ="),
    ):
        block = re.search(rf"CONSTRAINT {constraint} EXCLUDE USING gist \((.*?)\) WHERE", sql, re.S)
        assert block and keys in block.group(1), constraint
    assert sql.count("WHERE (retired_at IS NULL)") == 4
    assert "FOREIGN KEY (security_identifier_id, symbol)" in sql
    assert "REFERENCES security_identifier (security_identifier_id, symbol)" in sql
    assert (
        sql.count("reference_raw_id uuid NOT NULL REFERENCES reference_raw(reference_raw_id)") == 2
    )
    assert "vendor text NOT NULL CHECK (vendor IN ('massive'))" in sql


def test_unretired_spans_resolve_only_to_unretired_identifiers():
    sql = _sql()
    assert "BEFORE INSERT ON ticker_event" in sql
    assert "BEFORE UPDATE ON security_identifier" in sql
    assert sql.count("EXECUTE FUNCTION ticker_event_identity_unretired()") == 2


def test_figi_pattern_accepts_served_figis_and_refuses_vowels():
    pattern = re.search(r"ELSE value ~ '([^']+)'", _sql())
    assert pattern
    figi = re.compile(pattern.group(1))
    for served in ("BBG000C2V3D6", "BBG001SCTQY4", "BBG000KB2D74", "BBG001S8V781"):
        assert figi.match(served), served
    for bad in ("BBA001SCTQY4", "BBG001SCTQYA", "BBG001SCTQY", "bbg001sctqy4"):
        assert not figi.match(bad), bad


def test_seeds_the_measured_volume_epoch_only():
    sql = _sql()
    assert sql.count("INSERT INTO definition_epoch") == 1
    assert "SELECT 'massive', 'volume', DATE '2026-02-23'" in sql
    assert "WHERE NOT EXISTS" in sql


def test_no_compressed_hypertable_is_touched():
    sql = _sql()
    assert "ALTER COLUMN" not in sql
    assert "compress" not in sql.lower()
