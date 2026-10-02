"""CI guard: services/ohlcv_coverage_writer.py is the only writer of ohlcv_coverage.

Single-writer fence for the coverage ledger (migration 432, phase 189 CD-03): the ledger stays
in step with the stored bars only because every write happens in the writer module, inside the
bars' transaction or the fetcher's outcome write. A second INSERT/UPDATE/DELETE/COPY elsewhere
could drift it silently, so a new one fails here unless this allow-list is edited with a reason.

CI-clean: no DB, no network; pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_WRITER_PATTERN = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+ohlcv_coverage\b")
_SEARCH_DIRS = ("services", "src", "scripts")

_ALLOW_LIST: dict[str, str] = {
    "services/ohlcv_coverage_writer.py": (
        "PERMANENT: the single writer of ohlcv_coverage (phase 189 CD-03/CD-04): the "
        "upsert inside persist_chunk_atomically's transaction, the per-item outcome "
        "write and the --reset-failures path."
    ),
}


def test_every_ohlcv_coverage_writer_is_on_the_allow_list():
    hits = find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN)
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="ohlcv_coverage write(s)",
        remedy=(
            "Write the ledger through services/ohlcv_coverage_writer.py, never inline; it must "
            "stay in the bars' transaction to stay true."
        ),
    )


def test_coverage_writer_allow_list_has_no_stale_entries():
    hits = find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN)
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
