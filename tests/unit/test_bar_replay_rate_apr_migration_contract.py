"""Migration 595 contract: the bar replay provider's publish rate is an APR key, not an env var."""

from __future__ import annotations

import re

from services import bar_replay_provider
from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "595_bar_replay_rate_apr.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_KEY = "infra.bar_replay.bars_per_sec"


def test_migration_595_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_key_seeded_with_type_default_provenance_and_state():
    assert f"('{_KEY}', 'float', '10'" in _FLAT
    description = _FLAT.split(f"('{_KEY}', 'float'")[1].split("'),")[0]
    assert "[initial_estimate]" in description
    assert "Not an ML learning target" in description
    assert f"('{_KEY}', '10', 1)" in _FLAT


def test_provider_reads_the_seeded_key_and_its_default_matches():
    assert bar_replay_provider.RATE_BPS_KEY == _KEY
    assert bar_replay_provider.DEFAULT_RATE_BPS == 10.0


def test_no_environment_read_remains_in_the_provider():
    assert "os.environ" not in read_source("services", "bar_replay_provider.py")
