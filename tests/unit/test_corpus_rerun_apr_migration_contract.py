"""Migration 579 contract: the corpus rerun's APR seeds (plan 186-32 Task 1).

Reads the .sql text only (no DB), SQL line comments stripped, plus the one loader every rerun step
shares (services/corpus_rerun_apr.py).
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime

import numpy as np
import pytest

from services.backfill_feature_factory import _spool_line
from services.corpus_rerun_apr import CorpusRerunApr, load_corpus_rerun_apr
from src.config.config_service import ConfigService
from src.intelligence.features.feature_vector_persistence import (
    feature_vector_row_values,
    feature_vectors_numeric_columns,
)
from tests.unit._source_grep_helpers import read_source

_FILE = "579_corpus_rerun_apr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_TIMERS = (
    '["indicagent-ibkr-history-fetcher.timer", "indicagent-alpaca-nightly.timer", '
    '"indicagent-bar-derivation-daily.timer", "indicagent-bar-derivation-grid.timer"]'
)
_KEYS = (
    ("infra.corpus_rerun.max_disk_fraction", "float", "0.70", "[user_preference, lead 2026-11-05]"),
    ("infra.corpus_rerun.disk_reserve_bytes", "int", "50000000000", "[user_preference]"),
    ("infra.corpus_rerun.bytes_per_row_uncompressed", "int", "1379", "[rca_analysis]"),
    ("infra.corpus_rerun.compression_ratio", "float", "6.0", "[rca_analysis]"),
    ("infra.corpus_rerun.stored_bytes_per_spool_byte", "float", "0.37", "[initial_estimate]"),
    (
        "infra.corpus_rerun.data_gate.max_missing_session_fraction",
        "float",
        "0.01",
        "[initial_estimate]",
    ),
    (
        "infra.corpus_rerun.data_gate.max_missing_1d_session_fraction",
        "float",
        "0.01",
        "[initial_estimate]",
    ),
    ("infra.corpus_rerun.data_gate.min_session_bar_fraction", "float", "0.9", "[initial_estimate]"),
    ("infra.corpus_rerun.blocking_timers", "str", _TIMERS, "[user_preference]"),
)


def test_migration_579_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_every_key_seeded_with_its_value_type_provenance_and_state():
    for key, value_type, value, provenance in _KEYS:
        assert f"('{key}', '{value_type}', '{value}'" in _FLAT, key
        description = _FLAT.split(f"('{key}', '{value_type}'")[1].split("'),")[0]
        assert provenance in description, key
        assert "Not an ML learning target" in description, key
        assert f"('{key}', '{value}', 1)" in _FLAT, key


def test_only_the_rerun_keys_are_seeded():
    seeded = set(re.findall(r"\('(infra\.[a-z_.0-9]+)', '", _FLAT))
    assert seeded == {key for key, *_ in _KEYS}


def test_rerun_seed_is_idempotent_and_history_written_once():
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert "'migration_579'" in _FLAT
    assert "NOT EXISTS (SELECT 1 FROM config_history h" in _FLAT


def test_blocking_timers_seed_is_a_json_list_of_timer_units():
    timers = json.loads(_TIMERS)
    assert timers and all(t.startswith("indicagent-") and t.endswith(".timer") for t in timers)


def test_spool_ratio_seed_is_the_pilot_row_bytes_over_one_spool_row_rounded_up():
    """1379 stored bytes per row over the spool bytes of one fully populated row, rounded up to
    two decimals (the guard takes the larger of the seed and every measured ratio)."""
    n = len(feature_vectors_numeric_columns())
    values = np.random.default_rng(0).standard_normal(n).astype(np.float32).tolist()
    row = feature_vector_row_values(
        "SPY", "5m", datetime(2024, 1, 2, 14, 30, tzinfo=UTC), "bull", "low", values
    )
    spool_bytes = len(_spool_line(row).encode())
    assert math.ceil(1379 / spool_bytes * 100) / 100 == 0.37


def test_loader_reads_every_key_and_refuses_an_unseeded_one():
    cfg = ConfigService(database_url="")
    for key, value_type, value, _ in _KEYS:
        cfg._cache[key] = cfg._parse_value(value, value_type)
    apr = load_corpus_rerun_apr(cfg)
    assert apr == CorpusRerunApr(
        max_disk_fraction=0.70,
        disk_reserve_bytes=50_000_000_000,
        bytes_per_row_uncompressed=1379,
        compression_ratio=6.0,
        stored_bytes_per_spool_byte=0.37,
        max_missing_session_fraction=0.01,
        max_missing_1d_session_fraction=0.01,
        min_session_bar_fraction=0.9,
        blocking_timers=tuple(json.loads(_TIMERS)),
    )
    del cfg._cache["infra.corpus_rerun.compression_ratio"]
    with pytest.raises(KeyError, match="compression_ratio"):
        load_corpus_rerun_apr(cfg)
