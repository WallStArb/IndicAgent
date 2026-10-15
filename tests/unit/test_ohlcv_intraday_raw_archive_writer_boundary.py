"""CI guard: ohlcv_intraday_raw_archive has one writer (phase 185 plan 12, T-185-12-06).

The archive has no writer since phase 191 plan 08: the fetch path writes ohlcv_raw (plan 05)
and plan 08 deleted bar_derivation's archive-from-table INSERT ... SELECT with its owner module
services/intraday_raw_archive.py. The table stays read-only until plan 191-16 drops it; any
INSERT or COPY into it fails CI unless this allow-list is edited, which forces a justification
into the diff.

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

# (file, reason) -- every ohlcv_intraday_raw_archive write in the tree must appear here (none).
_ALLOW_LIST: dict[str, str] = {}


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
            "the archive is read-only until plan 191-16 drops it; vendor answers go to "
            "ohlcv_raw through the ingress contract. Only edit _ALLOW_LIST here with a "
            "review-ready reason."
        ),
    )


def test_archive_writer_allow_list_has_no_stale_entries():
    hits = _find_writer_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
