"""CI guard: ledger.py is the sole writer of research run records and construction identity.

Phase 183 D-05: `src/intelligence/research/ledger.py` is the only code that writes
`research_run` rows (migration 366) or inserts `concept_registry` rows with
`domain = 'construction'`. A second writer would bypass the advisory lock that makes the
spec-once check and the vintage budget count race-free, so any new file matching either
pattern fails here unless this allow-list is edited with a reason.

Test directories are not scanned: the integration test issues raw UPDATE and DELETE
statements on purpose, to prove the migration 366 triggers refuse them.

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

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SEARCH_DIRS = ("services", "src", "scripts", "production")
_FILE_GLOBS = ("*.py", "*.sql")

_RUN_WRITE_PATTERN = re.compile(
    r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+research_run\b", re.IGNORECASE | re.DOTALL
)
_CONSTRUCTION_IDENTITY_PATTERN = re.compile(
    r"INSERT\s+INTO\s+concept_registry\b[^;]{0,3000}?'construction'", re.IGNORECASE | re.DOTALL
)

_LEDGER = "src/intelligence/research/ledger.py"
_LEGACY_REASON = (
    "PERMANENT: legacy construction-domain verdict row inserted by migration before "
    "ledger.py became the sole writer (phase 183, D-05)"
)

_RUN_WRITE_ALLOW_LIST: dict[str, str] = {
    _LEDGER: "PERMANENT: the S6 sole writer of research_run (phase 183, D-05).",
}

_CONSTRUCTION_IDENTITY_ALLOW_LIST: dict[str, str] = {
    _LEDGER: "PERMANENT: the S6 sole writer of construction identity rows (phase 183, D-05).",
    "production/migrations/328_concept_registry_phase148_placement_verdict.sql": _LEGACY_REASON,
    "production/migrations/329_concept_registry_construction_domain.sql": _LEGACY_REASON,
    "production/migrations/330_concept_registry_residual_single_security_verdict.sql": (
        _LEGACY_REASON
    ),
    "production/migrations/333_concept_registry_bars_since_high_fast_verdict.sql": (_LEGACY_REASON),
    "production/migrations/334_concept_registry_range_pct_fast_single_name_verdict.sql": (
        _LEGACY_REASON
    ),
}

_REMEDY = (
    "Route the write through src/intelligence/research/ledger.py (it holds the advisory "
    "lock), or add the file to the allow-list here with a real reason."
)


def _hits(pattern: re.Pattern[str]) -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, pattern, _FILE_GLOBS)


def test_no_unlisted_research_run_writers() -> None:
    assert_no_unlisted_references(
        _hits(_RUN_WRITE_PATTERN),
        _RUN_WRITE_ALLOW_LIST,
        what="research_run writers",
        remedy=_REMEDY,
    )
    assert_no_unlisted_references(
        _hits(_CONSTRUCTION_IDENTITY_PATTERN),
        _CONSTRUCTION_IDENTITY_ALLOW_LIST,
        what="construction-domain concept_registry writers",
        remedy=_REMEDY,
    )


def test_allow_lists_have_no_stale_entries() -> None:
    assert_allow_list_has_no_stale_entries(_hits(_RUN_WRITE_PATTERN), _RUN_WRITE_ALLOW_LIST)
    assert_allow_list_has_no_stale_entries(
        _hits(_CONSTRUCTION_IDENTITY_PATTERN), _CONSTRUCTION_IDENTITY_ALLOW_LIST
    )
