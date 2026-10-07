"""Migration 449 contract: the 1d verdict report's tunable thresholds (plan 185-33 Task 1).

D7 (services/bar_reconciliation_audit.py) reads all three keys at init. Zero-tolerance checks
(policy_conformance, lineage_missing, canonical_recompute, digest_fresh) are definitions in code,
not keys. Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "449_bar_integrity_verdict_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_KEYS = (
    ("threshold.bar_integrity.session_coverage_min_1d", "float", "0.999"),
    ("threshold.bar_integrity.vendor_ratio_run_min_sessions", "int", "5"),
    ("threshold.bar_integrity.report_max_age_hours", "int", "30"),
)


def test_migration_449_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_three_keys_seeded_with_provenance_and_not_ml_targets():
    for key, value_type, value in _KEYS:
        assert f"('{key}', '{value_type}', '{value}'" in _FLAT, key
        description = _FLAT.split(f"('{key}', '{value_type}'")[1].split("'),")[0]
        assert "[initial_estimate]" in description, key
        assert "Not an ML learning target" in description, key
        assert f"('{key}', '{value}', 1)" in _FLAT, key


def test_only_the_keys_this_plan_reads():
    seeded = set(re.findall(r"\('(threshold\.[a-z_.0-9]+|infra\.[a-z_.0-9]+)', '", _FLAT))
    assert seeded == {key for key, _, _ in _KEYS}


def test_migration_449_seed_is_idempotent_and_history_written_once():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert "'migration_449'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT


def test_header_names_the_reader_and_the_zero_tolerance_definitions():
    header = _RAW.split("BEGIN;")[0]
    assert "bar_reconciliation_audit.py" in header
    assert "185-33" in header
    assert "section 6" in header
    for check in ("policy_conformance", "lineage_missing", "canonical_recompute", "digest_fresh"):
        assert check in header, check


def test_d7_reads_every_key():
    source = read_source("services", "bar_reconciliation_audit.py")
    for key, _, _ in _KEYS:
        assert f'"{key}"' in source, key
