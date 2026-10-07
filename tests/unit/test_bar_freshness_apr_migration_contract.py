"""Migration 455 contract: the freshness_1d lag threshold (plan 185-46 Task 3).

D7 judges freshness_1d against threshold.bar_integrity.freshness_max_lag_sessions_1d. Reads the
.sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "455_bar_freshness_1d_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_KEY = "threshold.bar_integrity.freshness_max_lag_sessions_1d"


def test_migration_455_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_one_int_key_seeded_with_provenance_and_not_an_ml_target():
    assert f"('{_KEY}', 'int', '2'" in _FLAT
    description = _FLAT.split(f"('{_KEY}', 'int'")[1].split("'),")[0]
    assert "[initial_estimate]" in description
    assert "Not an ML learning target" in description
    assert f"('{_KEY}', '2', 1)" in _FLAT


def test_no_other_key_is_touched():
    keys = set(re.findall(r"'((?:threshold|infra|alpha|alert)\.[a-z0-9_.]+)'", _CODE))
    assert keys == {_KEY}
    assert "UPDATE" not in _CODE and "DELETE" not in _CODE


def test_freshness_seed_is_idempotent_and_history_written_once():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert _FLAT.count("INSERT INTO config_history") == 1
    assert "'migration_455'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT


def test_header_names_the_reader_and_the_gate():
    header = _RAW.split("BEGIN;")[0]
    assert "bar_reconciliation_audit.py" in header
    assert "REBUILD_ONLY_CHECKS" in header
    assert "185-46" in header
