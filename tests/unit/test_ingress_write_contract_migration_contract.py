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
