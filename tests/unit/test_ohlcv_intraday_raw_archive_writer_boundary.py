"""CI guard: ohlcv_intraday_raw_archive has one writer (phase 185 plan 12, T-185-12-06).

services/intraday_raw_archive.py is the single owner module of the raw
intraday archive: it holds bar_derivation's archive-from-table INSERT ...
SELECT (moved there byte-identical in plan 12) and insert_fetched_archive_rows()
for fetched chunks. BarDerivation and the backfill persist helper both call
into it; any other INSERT or COPY into the table fails CI unless this
allow-list is edited, which forces a single-writer justification into the diff.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_WRITER_PATTERN = re.compile(r"\b(?:INSERT\s+INTO|COPY)\s+ohlcv_intraday_raw_archive\b")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every ohlcv_intraday_raw_archive write in the tree must appear here.
_ALLOW_LIST: dict[str, str] = {
    "services/intraday_raw_archive.py": (
        "PERMANENT: the single owner module of the raw intraday archive (phase 185 "
        "plan 12, single_writer / T-185-12-06). Holds the archive-from-table INSERT "
        "... SELECT (moved byte-identical out of bar_derivation) and "
        "insert_fetched_archive_rows() for fetched chunks; BarDerivation and the "
        "backfill persist helper both route through this module."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_writer_references() -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN, file_globs=("*.py",))


def test_every_archive_writer_is_on_the_allow_list():
    hits = _find_writer_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="`ohlcv_intraday_raw_archive` write(s)",
        remedy=(
            "services/intraday_raw_archive.py is the table's only writer (plan 12, "
            "single_writer). If this is a genuine new write path, route it through "
            "that module instead; only edit _ALLOW_LIST here with a review-ready "
            "reason for making it a second writer."
        ),
    )


def test_archive_writer_allow_list_has_no_stale_entries():
    hits = _find_writer_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
