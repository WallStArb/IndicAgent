"""Unit tests for the D-38 Postgres settings baseline script (phase 186 plan 05).

Covers the pure functions only -- compose parsing and running-vs-compose drift
comparison -- with a temp compose file and fake pg_settings-shaped rows. No DB,
no docker (the script's main() is the only thing that touches either).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.ops.db.ops_pg_settings_baseline import (
    compare_settings,
    normalize_setting_bytes,
    parse_compose_command_settings,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_COMPOSE = _REPO_ROOT / "production" / "docker-compose.yml"

_NO_DASH_C_COMPOSE = """
services:
  timescaledb:
    command: ["postgres", "--foo", "bar"]
"""

_DASH_C_COMPOSE = """
services:
  timescaledb:
    shm_size: '512m'
    command: ["postgres", "-c", "work_mem=64MB", "-c", "shared_buffers=3GB"]
  other:
    command: ["postgres", "-c", "work_mem=1MB"]
"""


def _write_compose(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "docker-compose.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_compose_command_settings_real_file():
    settings = parse_compose_command_settings(_REAL_COMPOSE)
    assert settings["shared_buffers"] == "3GB"
    assert settings["work_mem"] == "64MB"
    assert settings["max_connections"] == "200"
    assert settings["__shm_size"] == "512m"


def test_parse_compose_command_settings_without_dash_c_pairs_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        compose = _write_compose(Path(td), _NO_DASH_C_COMPOSE)
        assert parse_compose_command_settings(compose) == {}


def test_parse_compose_command_settings_collects_dash_c_and_shm_size():
    with tempfile.TemporaryDirectory() as td:
        compose = _write_compose(Path(td), _DASH_C_COMPOSE)
        settings = parse_compose_command_settings(compose)
        # Only the requested service ("timescaledb") is walked, not "other".
        assert settings == {
            "work_mem": "64MB",
            "shared_buffers": "3GB",
            "__shm_size": "512m",
        }


def test_compare_settings_reports_work_mem_drift():
    running = {
        "work_mem": {
            "setting": "8192",
            "unit": "kB",
            "source": "command line",
            "sourcefile": None,
        }
    }
    entries = compare_settings({"work_mem": "64MB"}, running)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "work_mem"
    assert entry["status"] == "drift"
    assert entry["compose"] == "64MB"
    assert entry["running"] == "8MB"
    assert entry["source"] == "command line"


def test_compare_settings_normalizes_units_before_comparing():
    # "3GB" and 393216 x 8kB are the same byte count (3221225472).
    running = {
        "shared_buffers": {
            "setting": "393216",
            "unit": "8kB",
            "source": "command line",
            "sourcefile": None,
        }
    }
    entries = compare_settings({"shared_buffers": "3GB"}, running)
    assert [e["status"] for e in entries] == ["match"]
    assert not [e for e in entries if e["status"] == "drift"]


def test_compare_settings_reports_absent_key_as_unknown():
    entries = compare_settings({"work_mem": "64MB"}, {})
    assert [e["status"] for e in entries] == ["unknown"]


def test_normalize_setting_bytes_returns_none_for_non_memory():
    assert normalize_setting_bytes("200", "") is None  # max_connections
    assert normalize_setting_bytes("posix", "") is None  # dynamic_shared_memory_type


def test_normalize_setting_bytes_handles_units_and_suffixes():
    assert normalize_setting_bytes("393216", "8kB") == 3221225472
    assert normalize_setting_bytes("8192", "kB") == 8388608
    assert normalize_setting_bytes("64MB", "") == 67108864
    assert normalize_setting_bytes("3GB", "") == 3221225472
