"""Migration 448 contract: the ingress write contract's schema (plan 185-39).

Reads the .sql text only (no DB), SQL line comments stripped. The live and replayed behavior is
proved by tests/integration/test_ingress_write_contract.py under the real roles.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "448_ingress_write_contract.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_runs_in_one_transaction_with_a_lock_timeout():
    assert "SET lock_timeout" in _CODE.split("BEGIN;")[0]
    assert _CODE.rstrip().endswith("COMMIT;")


def test_request_digest_column_is_nullable_and_a_sha256_hex():
    assert "ALTER TABLE ohlcv_request ADD COLUMN IF NOT EXISTS content_digest text;" in _FLAT
    assert "content_digest IS NULL OR content_digest ~ '^[0-9a-f]{64}$'" in _FLAT
    assert "content_digest text NOT NULL" not in _FLAT


def test_archive_refuses_delete_only_and_the_append_only_row_trigger_is_replaced():
    assert (
        "DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_append_only "
        "ON ohlcv_intraday_raw_archive;"
    ) in _FLAT
    assert "BEFORE DELETE ON ohlcv_intraday_raw_archive FOR EACH ROW" in _FLAT
    assert "BEFORE UPDATE" not in _FLAT
    # The statement TRUNCATE trigger of migration 383 stays: this file does not touch it.
    assert "no_truncate" not in _FLAT


def test_update_is_granted_to_the_bar_writer_role_only():
    assert "GRANT UPDATE ON ohlcv_intraday_raw_archive TO bar_derivation_writer;" in _FLAT
    assert _FLAT.count("GRANT") == 1


def test_no_compressed_column_type_change_so_no_vacuum_is_owed():
    assert "ALTER COLUMN" not in _FLAT.upper()


def test_header_names_the_plan_and_the_number_claims():
    header = re.sub(r"\s*--\s*|\s+", " ", _RAW.split("SET lock_timeout")[0])
    assert "185-39" in header and "sections 3 and 4" in header


# --- Migration 475 (phase 191 plan 04): NOT NULL vendor/kind and the widened revision key ---

_VK_FILE = "475_ohlcv_revision_vendor_kind_key.sql"
_VK_RAW = read_source("production", "migrations", _VK_FILE)
_VK_CODE = re.sub(r"--[^\n]*", "", _VK_RAW)
_VK_FLAT = re.sub(r"\s+", " ", _VK_CODE)


def test_vendor_kind_migration_is_one_transaction_with_a_lock_timeout():
    assert "SET lock_timeout" in _VK_CODE.split("BEGIN;")[0]
    assert _VK_CODE.rstrip().endswith("COMMIT;")


def test_vendor_kind_become_not_null_after_a_loud_null_check():
    assert "ALTER COLUMN vendor SET NOT NULL, ALTER COLUMN kind SET NOT NULL" in _VK_FLAT
    assert "RAISE EXCEPTION" in _VK_FLAT
    assert _VK_FLAT.index("RAISE EXCEPTION") < _VK_FLAT.index("SET NOT NULL")


def test_primary_key_admits_two_kinds_restated_by_one_load():
    assert 'PRIMARY KEY (load_id, symbol, timeframe, "timestamp", vendor, kind)' in _VK_FLAT
    assert "DROP CONSTRAINT ohlcv_revision_pkey" in _VK_FLAT


def test_ordinary_table_so_no_vacuum_is_owed():
    assert "VACUUM" not in _VK_CODE.upper()
    assert "decompress" not in _VK_CODE.lower()
