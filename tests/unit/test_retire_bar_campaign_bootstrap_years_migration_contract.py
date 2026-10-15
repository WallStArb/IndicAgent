"""Source-level contract for migration 490 (plan 191-11): retire infra.bar_campaign.bootstrap_years.

Plan 191-11 deleted ops_d1_bootstrap.py, the key's only reader. The migration deletes the key from
config_history, then config_state, then config_schema, in one transaction, by literal key
(idempotent). CI-clean: reads files only.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import read_source

_MIGRATION = ("production", "migrations", "490_retire_bar_campaign_bootstrap_years_apr.sql")
_KEY = "infra.bar_campaign.bootstrap_years"
_REPO_ROOT = Path(__file__).parent.parent.parent


def _statements() -> list[str]:
    sql = re.sub(r"--[^\n]*", "", read_source(*_MIGRATION))
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def test_bootstrap_years_retirement_deletes_history_state_schema_in_one_transaction() -> None:
    statements = _statements()
    assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
    body = statements[1:-1]
    assert [s.split()[2] for s in body] == ["config_history", "config_state", "config_schema"]
    assert all(f"'{_KEY}'" in s for s in body)


def test_no_reader_of_bootstrap_years_remains() -> None:
    for root in ("scripts", "services", "src"):
        for path in (_REPO_ROOT / root).rglob("*.py"):
            assert _KEY not in path.read_text(encoding="utf-8"), path
