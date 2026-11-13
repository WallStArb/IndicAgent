"""CI guard: services/, scripts/ and src/ import the history protocol, never a concrete leaf.

Phase 190 (provider history plane unification): a vendor is a leaf
(`src/providers/<vendor>.py`) and the batch fetcher dispatches through the
`HistoryProvider` protocol in `src/providers/base.py`. A concrete-leaf import
outside `src/providers/` reintroduces the vendor-coupled fetch paths this
phase exists to delete, the same way raw `market_data_ohlcv` reads kept
reappearing before test_market_data_ohlcv_boundary.py (the mechanism copied
here, via tests/unit/_source_grep_helpers.py).

Two import forms bind a concrete leaf and both are fenced:
  from src.providers.ibkr import IBKRProvider      (direct module path)
  from src.providers import IBKRProvider           (package-level symbol; the
                                                    package __init__ re-exports
                                                    the leaf)
`from src.providers.base import ...` stays legal everywhere -- importing the
protocol is the point. The scan covers services/, scripts/ and src/ but
excludes src/providers/ itself: that ring owns the leaves and their adapter,
so leaf-to-leaf references are not boundary violations.

Adding a new concrete-leaf import requires adding a row to _ALLOW_LIST with a
real reason, at review time, in the diff itself.

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
# Direct module-path import of a leaf module ("ibkr_adapter" deliberately does
# not match: the \\b requires the exact module name).
_LEAF_MODULE_PATTERN = re.compile(r"(?:from|import)\s+src\.providers\.(?:ibkr|alpaca)\b")
# Package-level import that binds a leaf symbol or the leaf module itself
# ("from src.providers import IBKRProvider, ibkr"); protocol-only imports
# (DataProvider, HistoryProvider, OHLCVBar, ...) do not match.
_LEAF_SYMBOL_PATTERN = re.compile(
    r"from\s+src\.providers\s+import\s+[^#\n]*\b(?:ibkr|IBKRProvider|alpaca|AlpacaProvider)\b"
)
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every concrete-leaf import in the tree must appear here.
# Adding a new call site requires adding a row here with a real reason, not
# just silencing the test. NOTE (post 190-04): the fetcher dispatches through
# the provider registry (entry.fetch per item), but the loop never constructs a
# foreign leaf, so the three fetcher-family entries stay: the registry's ibkr
# entry owns the concrete leaf construction, and the two helper modules hold the
# IBKR mechanics and constants that entry drives. Moving the leaf factory into
# src/providers (an entry the registry imports through the protocol surface)
# would shrink the first row.
_ALLOW_LIST: dict[str, str] = {}


@functools.lru_cache(maxsize=1)
def _find_concrete_leaf_imports() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py file under _SEARCH_DIRS
    that imports a concrete provider leaf by either form, excluding src/providers/
    itself (that ring owns the leaves)."""
    hits: dict[str, int] = {}
    for pattern in (_LEAF_MODULE_PATTERN, _LEAF_SYMBOL_PATTERN):
        for path, count in find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, pattern).items():
            if path.startswith("src/providers/"):
                continue
            hits[path] = hits.get(path, 0) + count
    return hits


def test_every_concrete_leaf_import_is_on_the_allow_list():
    hits = _find_concrete_leaf_imports()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="concrete provider-leaf import(s)",
        remedy=(
            "Import the protocol instead (`from src.providers.base import "
            "HistoryProvider`, or the package-level DataProvider/HistoryProvider/"
            "OHLCVBar exports) and dispatch through it. If a file genuinely needs "
            "the concrete leaf, add it to _ALLOW_LIST in this file with a one-line "
            "reason."
        ),
    )


def test_leaf_boundary_allow_list_has_no_stale_entries():
    hits = _find_concrete_leaf_imports()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
