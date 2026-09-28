"""CI guard: services/_batch_utils.py bulk_load is the sole writer of provenance_batch.

Phase 186 D-24: `provenance_batch` (migration 386) is written only by
`services/_batch_utils.py bulk_load`. A second writer would bypass the advisory
lock, the idempotency rule and the guard-trigger lifecycle, so any new file
matching the pattern fails here unless this allow-list is edited with a reason.

Test directories are not scanned: the integration test issues raw UPDATE and
DELETE statements on purpose, to prove the migration 386 triggers refuse them.

CI-clean: no DB, no network, pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent  # tests/unit/ -> repo root
_SEARCH_DIRS = ("services", "src", "scripts", "production")
_FILE_GLOBS = ("*.py", "*.sql")

_PROVENANCE_BATCH_WRITE_PATTERN = re.compile(
    r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+provenance_batch\b", re.IGNORECASE | re.DOTALL
)

_ALLOW_LIST: dict[str, str] = {
    "services/_batch_utils.py": "PERMANENT: sole writer of provenance_batch, D-24.",
    "production/migrations/386_provenance_batch.sql": (
        "PERMANENT: creates the table and guard triggers (its sole-writer rule comment "
        "matches the pattern)"
    ),
}

_REMEDY = (
    "Route the write through services/_batch_utils.py bulk_load (it holds the batch-key "
    "advisory lock and owns the provenance lifecycle), or add the file to the allow-list "
    "here with a real reason."
)


def _hits() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _PROVENANCE_BATCH_WRITE_PATTERN, _FILE_GLOBS
    )


def test_no_unlisted_provenance_batch_writers() -> None:
    assert_no_unlisted_references(
        _hits(), _ALLOW_LIST, what="provenance_batch writers", remedy=_REMEDY
    )


def test_provenance_batch_allow_list_has_no_stale_entries() -> None:
    assert_allow_list_has_no_stale_entries(_hits(), _ALLOW_LIST)
