"""Source-level contract for migration 434 (plan 189-08): retire the IBKR history lease APR keys.

Plan 189-08 deleted the historical pipeline's CLI and its ibkr_history_stream ResourceLease, the
only readers of infra.ibkr_history_lease.nightly_wait_minutes and
infra.ibkr_history_lease.priority_wait_minutes; FetcherLock is fail-fast and has no wait. The
migration deletes both keys from config_history, then config_state, then config_schema, inside one
transaction, by literal key (idempotent: a rerun deletes nothing). CI-clean: reads the file only.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import read_source

_MIGRATION = ("production", "migrations", "434_retire_ibkr_history_lease_apr.sql")
_KEYS = (
    "infra.ibkr_history_lease.nightly_wait_minutes",
    "infra.ibkr_history_lease.priority_wait_minutes",
)
_REPO_ROOT = Path(__file__).parent.parent.parent


def _statements() -> list[str]:
    sql = re.sub(r"--[^\n]*", "", read_source(*_MIGRATION))
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def test_deletes_history_then_state_then_schema_in_one_transaction():
    statements = _statements()
    assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
    body = statements[1:-1]
    assert [s.split()[2] for s in body] == ["config_history", "config_state", "config_schema"]
    for statement in body:
        assert statement.startswith("DELETE FROM ")
        for key in _KEYS:
            assert f"'{key}'" in statement
        assert "LIKE" not in statement.upper()


def test_touches_only_the_two_lease_keys():
    literals = set(re.findall(r"'([^']+)'", " ".join(_statements())))
    assert literals == set(_KEYS)


def test_no_reader_is_left_in_code():
    for search_dir in ("services", "src", "scripts"):
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
            assert "ibkr_history_lease" not in path.read_text(encoding="utf-8"), path


def test_header_cites_the_plan_and_the_grep():
    header = read_source(*_MIGRATION).split("BEGIN;")[0]
    assert "189-08" in header
    assert 'grep -rn "ibkr_history_lease" services src scripts' in header
