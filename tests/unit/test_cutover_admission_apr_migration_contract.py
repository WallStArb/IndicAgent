"""Migration 454 contract: the d2-v2 cutover's admission and review keys (plan 185-38 Task 0).

Tradier is a name's primary 1d source only on evidence (scripts/ops/bars/ops_source_policy.py
--admission-sweep reads the two admission keys); the first apply runs only after
the one-off cutover review (deleted in 185-42) passed the dry-run TSV against the two cutover keys.
Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "454_cutover_admission_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_KEYS = (
    ("threshold.bar_integrity.tradier_admission_min_overlap_sessions", "int", "60"),
    ("threshold.bar_integrity.tradier_admission_min_agree_share", "float", "0.9"),
    ("threshold.bar_integrity.cutover_max_removed_share", "float", "0.005"),
    ("threshold.bar_integrity.cutover_max_refused_share", "float", "0.005"),
)


def test_migration_454_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_four_keys_seeded_with_provenance_and_not_ml_targets():
    for key, value_type, value in _KEYS:
        assert f"('{key}', '{value_type}', '{value}'" in _FLAT, key
        description = _FLAT.split(f"('{key}', '{value_type}'")[1].split("'),")[0]
        assert "[initial_estimate]" in description, key
        assert "Not an ML learning target" in description, key
        assert f"('{key}', '{value}', 1)" in _FLAT, key


def test_seed_is_idempotent_and_history_written_once():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert "'migration_454'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT


def test_header_names_the_readers():
    header = _RAW.split("BEGIN;")[0]
    assert "ops_source_policy.py" in header
    assert "185-38" in header
