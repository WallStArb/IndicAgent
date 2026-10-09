"""Source-level contract for migration 457 (plan 185-48): retire the Tradier loader's APR keys.

Plan 185-48 deleted the Tradier daily loader, the only reader of
the six infra.tradier.* keys left after migration 459 retired max_changed_bar_ratio. The Tradier
account is unfunded and will not be funded (owner, 2026-10-07), so no fetch path reads them again.
The migration deletes the six keys from config_history, then config_state, then config_schema,
inside one transaction, by literal key (idempotent: a rerun deletes nothing). The cutover
admission keys threshold.bar_integrity.tradier_admission_* stay: ops_source_policy.py reads them
to judge the stored Tradier history. CI-clean: reads the file only.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import read_source

_MIGRATION = ("production", "migrations", "457_retire_tradier_apr.sql")
_KEYS = (
    "infra.tradier.concurrency",
    "infra.tradier.first_date_tolerance_days",
    "infra.tradier.history_start",
    "infra.tradier.min_session_ratio",
    "infra.tradier.nightly_enabled",
    "infra.tradier.request_timeout_s",
)
_REPO_ROOT = Path(__file__).parent.parent.parent


def _statements() -> list[str]:
    sql = re.sub(r"--[^\n]*", "", read_source(*_MIGRATION))
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def test_tradier_retirement_deletes_history_then_state_then_schema_in_one_transaction():
    statements = _statements()
    assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
    body = statements[1:-1]
    assert [s.split()[2] for s in body] == ["config_history", "config_state", "config_schema"]
    for statement in body:
        assert statement.startswith("DELETE FROM ")
        for key in _KEYS:
            assert f"'{key}'" in statement
        assert "LIKE" not in statement.upper()


def test_touches_only_the_six_tradier_loader_keys():
    literals = set(re.findall(r"'([^']+)'", " ".join(_statements())))
    assert literals == set(_KEYS)


def test_no_tradier_loader_key_reader_is_left_in_code():
    for search_dir in ("services", "src", "scripts"):
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
            assert "infra.tradier." not in path.read_text(encoding="utf-8"), path


def test_names_no_market_data_table():
    code = " ".join(_statements()).lower()
    for table in (
        "ohlcv_observation",
        "ohlcv_request",
        "ohlcv_load",
        "market_data_ohlcv",
        "bar_source_policy",
    ):
        assert table not in code


def test_tradier_retirement_header_cites_the_plan_and_the_grep():
    header = read_source(*_MIGRATION).split("BEGIN;")[0]
    assert "185-48" in header
    assert 'grep -rn "infra.tradier" services src scripts' in header
