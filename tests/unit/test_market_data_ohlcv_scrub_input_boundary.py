"""CI guard: no new `market_data_ohlcv_scrub_input` reads outside this allow-list.

The scrub-input view (migration 381, phase 185 plan 04) exists for the D2a scrub
and D5 seam stages only: it serves every traded bar INCLUDING quarantined ones,
because those stages must re-judge bars the tradeable view hides. Every other
reader wants tradeable bars and must use `market_data_ohlcv_tradeable` -- reading
the scrub-input view would silently reintroduce known-corrupt prints into
compute and measurement paths (the exact gap the raw-table guard closes for
synthetic fills). Same grep shape as test_market_data_ohlcv_boundary.py; test
files are not scanned, so the allow-list covers only services/src/scripts.

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
_SCRUB_INPUT_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+market_data_ohlcv_scrub_input\b")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every scrub-input view reference in the tree must appear here.
# Plan 15's seam-stage scripts add their own rows in their own commit.
_ALLOW_LIST: dict[str, str] = {
    "services/bar_scrub.py": (
        "PERMANENT: the D2a scrub pass's own read boundary (phase 185 plan 10, D-08/"
        "D-12). It must see every traded bar, quarantined included, to re-judge and "
        "re-write flags for bars the tradeable view hides; writes go to "
        "bar_quality_flag only, never market_data_ohlcv (D-09)."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_scrub_input_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py/.sh file under
    _SEARCH_DIRS that reads from the scrub-input view."""
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _SCRUB_INPUT_PATTERN, file_globs=("*.py", "*.sh")
    )


def test_every_scrub_input_reference_is_on_the_allow_list():
    hits = _find_scrub_input_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="`market_data_ohlcv_scrub_input` read(s)",
        remedy=(
            "If this is not a scrub/seam stage, point it at "
            "`market_data_ohlcv_tradeable` instead (the scrub-input view includes "
            "quarantined bars and exists for the D2a scrub and D5 seam stages only). "
            "Otherwise add it to _ALLOW_LIST in this file with a one-line reason."
        ),
    )


def test_scrub_input_allow_list_has_no_stale_entries():
    hits = _find_scrub_input_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
