"""CI guard: ohlcv_raw has one writer (phase 191 plan 02, single_writer).

services/ohlcv_raw_writer.py is the single owner of INSERT, UPDATE and COPY into ohlcv_raw (DELETE
too: no writer removes raw rows outside the allow-list): it classifies
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
_WRITER_PATTERN = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+ohlcv_raw\b")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every ohlcv_raw write in the tree must appear here.
_ALLOW_LIST: dict[str, str] = {
    "services/ohlcv_raw_writer.py": (
        "PERMANENT: the single owner of ohlcv_raw writes (phase 191 plan 02, single_writer). "
        "write_raw classifies by the same (vendor, kind) key, inserts new rows, replaces "
        "changed rows last-wins and logs the old values to ohlcv_revision."
    ),
    "scripts/ops/bars/ops_tradier_delete.py": (
        "TEMPORARY retire: 191-25 (Tradier source-scoped deletion, owner exception 2026-10-12). "
        "DELETE FROM ohlcv_raw where vendor tradier and timeframe 1d only, in symbol batches "
        "after the COPY backup (plan 191-20); it never inserts or updates a row."
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


def test_the_raw_pattern_catches_each_write_form():
    assert _WRITER_PATTERN.search("INSERT INTO ohlcv_raw (symbol)")
    assert _WRITER_PATTERN.search("UPDATE ohlcv_raw SET close = 1")
    assert _WRITER_PATTERN.search("DELETE FROM ohlcv_raw WHERE vendor = 'x'")
    assert _WRITER_PATTERN.search("COPY ohlcv_raw FROM STDIN")
    assert not _WRITER_PATTERN.search("SELECT * FROM ohlcv_raw")
    assert not _WRITER_PATTERN.search("COPY (SELECT * FROM ohlcv_raw) TO STDOUT")
