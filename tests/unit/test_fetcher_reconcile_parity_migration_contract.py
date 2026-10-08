"""Migration 451 contract: the fetcher's lane and parity keys (plan 189-10 Task 1, as amended).

Reads the .sql text only (no DB), SQL line comments stripped. Every new key is an int with its
provenance tag and is not an ML target; the 1d overlap key is the renamed
infra.bar_derivation.overlap_sessions (state and history kept); two descriptions that named
deleted machinery are rewritten (189-08 deferred item 6).
"""

from __future__ import annotations

import re

import pytest

from scripts.infrastructure.backfill import _fetch_queue as fq
from tests.unit._migration_catalog import migration_catalog
from tests.unit._source_grep_helpers import read_source

_FILE = "451_fetcher_reconcile_and_parity_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_NEW_KEYS = {
    "infra.backfill.ibkr_1d_reconcile_interval_days": ("1", "[user_preference]"),
    "infra.backfill.update_overlap_days_5m": ("3", "[initial_estimate]"),
    "infra.backfill.gap_fill_interval_days": ("7", "[initial_estimate]"),
    "infra.backfill.grid_parity_sample_names_per_week": ("10", "[initial_estimate]"),
}
_OLD_OVERLAP = "infra.bar_derivation.overlap_sessions"
_NEW_OVERLAP = "infra.backfill.update_overlap_sessions_1d"
_DESCRIBED = ("infra.ibkr.historical_request_timeout_sec", "infra.backfill.default_scopes")


def _description(key: str) -> str:
    return _FLAT.split(f"('{key}', 'int'")[1].split("'),")[0]


def test_migration_451_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


@pytest.mark.parametrize("key", sorted(_NEW_KEYS))
def test_every_new_key_is_an_int_with_its_seed_provenance_and_not_an_ml_target(key):
    seed, provenance = _NEW_KEYS[key]
    assert f"('{key}', 'int', '{seed}'" in _FLAT
    description = _description(key)
    assert description.lstrip(" ,0123456789'").startswith(provenance)
    assert "Not an ML learning target" in description
    assert f"('{key}', '{seed}', 1)" in _FLAT


def test_the_reconcile_interval_is_the_owner_decision_not_the_design_doc_week():
    description = _description("infra.backfill.ibkr_1d_reconcile_interval_days")
    assert "owner decision 2026-10-07" in description
    assert "('infra.backfill.ibkr_1d_reconcile_interval_days', 'int', '7'" not in _FLAT


def test_the_1d_overlap_key_is_renamed_with_state_and_history_kept():
    for table in ("config_schema", "config_state", "config_history"):
        assert f"UPDATE {table} SET config_key = '{_NEW_OVERLAP}'" in _FLAT
    assert _FLAT.count(f"WHERE config_key = '{_OLD_OVERLAP}'") == 3
    assert "DELETE" not in _CODE
    tail = _FLAT.split(f"SET config_key = '{_NEW_OVERLAP}',")[1].split("WHERE")[0]
    assert "[initial_estimate]" in tail and "Not an ML learning target" in tail


def test_the_catalog_sees_the_rename_and_every_new_key():
    _, keys = migration_catalog()
    assert _OLD_OVERLAP not in keys
    assert _NEW_OVERLAP in keys
    assert set(_NEW_KEYS) <= keys


def test_seeds_are_idempotent_and_history_is_written_once_per_key():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert _FLAT.count("INSERT INTO config_history") == 1
    assert "'migration_451'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT
    history = _FLAT.split("INSERT INTO config_history")[1].split(";")[0]
    for key in [*_NEW_KEYS, _NEW_OVERLAP]:
        assert f"'{key}'" in history


@pytest.mark.parametrize("key", _DESCRIBED)
def test_deferred_item_6_descriptions_no_longer_name_deleted_machinery(key):
    update = _FLAT.split(f"WHERE config_key = '{key}'")[0].rsplit("UPDATE config_schema", 1)[1]
    assert "SET description = '" in update
    for stale in ("backfill_retry_loop", "PAUSE_5M", "nightly legs", "todo 449"):
        assert stale not in update


def test_only_the_named_keys_are_touched():
    keys = set(re.findall(r"'((?:threshold|infra|alpha|alert)\.[a-z0-9_.]+)'", _CODE))
    assert keys == {*_NEW_KEYS, _OLD_OVERLAP, _NEW_OVERLAP, *_DESCRIBED}


def test_the_queue_reads_every_lane_key():
    """The migration seeds exactly the keys load_lane_config requires (no orphan, no gap)."""
    assert set(fq.LANE_KEYS) == {*_NEW_KEYS, _NEW_OVERLAP, fq.BASIS_TOLERANCE_KEY}


def test_header_names_the_readers_and_the_measured_tolerance():
    header = _RAW.split("BEGIN;")[0]
    assert "ibkr_history_fetcher.py" in header and "_fetch_queue.py" in header
    assert "fallback_basis_tolerance_bp" in header
    assert "5,558 pairs" in header
    assert "189-10" in header and "185-46" in header
