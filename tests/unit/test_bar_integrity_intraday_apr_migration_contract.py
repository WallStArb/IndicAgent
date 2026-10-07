"""Migration 450 contract: the intraday integrity checks' two keys (plan 185-40 Task 2).

D7 (services/bar_reconciliation_audit.py) reads both keys at init. Reads the .sql text only
(no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "450_bar_integrity_intraday_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_KEYS = (
    ("threshold.bar_integrity.slot_coverage_min_intraday", "float", "0.995", "[rca_analysis]"),
    ("infra.bar_integrity.intraday_full_sweep_days", "int", "7", "[conventional]"),
)


def test_migration_450_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_two_keys_seeded_with_provenance_and_not_ml_targets():
    for key, value_type, value, provenance in _KEYS:
        assert f"('{key}', '{value_type}', '{value}'" in _FLAT, key
        description = _FLAT.split(f"('{key}', '{value_type}'")[1].split("'),")[0]
        assert provenance in description, key
        assert "Not an ML learning target" in description, key
        assert f"('{key}', '{value}', 1)" in _FLAT, key


def test_only_the_intraday_keys_this_plan_reads():
    seeded = set(re.findall(r"\('(threshold\.[a-z_.0-9]+|infra\.[a-z_.0-9]+)', '", _FLAT))
    assert seeded == {key for key, *_ in _KEYS}


def test_migration_450_seed_is_idempotent_and_history_written_once():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert "'migration_450'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT


def test_header_names_the_reader_and_the_plan():
    header = _RAW.split("BEGIN;")[0]
    assert "bar_reconciliation_audit.py" in header
    assert "185-40" in header


def test_d7_reads_every_intraday_key():
    source = read_source("services", "bar_reconciliation_audit.py")
    for key, *_ in _KEYS:
        assert f'"{key}"' in source, key
