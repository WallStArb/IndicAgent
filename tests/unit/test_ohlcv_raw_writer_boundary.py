"""CI guard: ohlcv_raw has one writer (phase 191 plan 02, single_writer).

services/ohlcv_raw_writer.py is the single owner of INSERT and COPY into ohlcv_raw: it classifies
each vendor answer against the same (vendor, kind) key and logs restatements. Any other write
fails CI unless the allow-list is edited with a single-writer justification. The plan 03 one-shot
backfill adds its own entry when that file exists.

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
_WRITER_PATTERN = re.compile(r"\b(?:INSERT\s+INTO|COPY)\s+ohlcv_raw\b")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every ohlcv_raw write in the tree must appear here.
_ALLOW_LIST: dict[str, str] = {
    "services/ohlcv_raw_writer.py": (
        "PERMANENT: the single owner of ohlcv_raw writes (phase 191 plan 02, single_writer). "
        "write_raw classifies by the same (vendor, kind) key, inserts new rows, replaces "
        "changed rows last-wins and logs the old values to ohlcv_revision."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_writer_references() -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN, file_globs=("*.py",))


def test_every_ohlcv_raw_writer_is_on_the_allow_list():
    assert_no_unlisted_references(
        _find_writer_references(),
        _ALLOW_LIST,
        what="`ohlcv_raw` write(s)",
        remedy=(
            "services/ohlcv_raw_writer.py is the table's only writer; route the write through "
            "write_raw, or edit _ALLOW_LIST with a review-ready reason for a second writer."
        ),
    )


def test_ohlcv_raw_writer_allow_list_has_no_stale_entries():
    assert_allow_list_has_no_stale_entries(_find_writer_references(), _ALLOW_LIST)
