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
# just silencing the test. NOTE: the three fetcher-family entries
# (ibkr_history_fetcher.py, _history_fetch.py, _history_fetch_item.py) are
# expected to leave this list in plan 190-04, when the fetch path dispatches
# through the HistoryProvider protocol seam.
_ALLOW_LIST: dict[str, str] = {
    "scripts/infrastructure/backfill/ibkr_history_fetcher.py": (
        "SHRINKS IN 190-04: the phase 189/190 drain fetcher constructs IBKRProvider "
        "through its provider_factory seam and drives the item mechanics directly; "
        "its default provider becomes a protocol-resolved leaf registry at the "
        "190-04 seam and this entry leaves the list."
    ),
    "scripts/infrastructure/backfill/_history_fetch.py": (
        "SHRINKS IN 190-04: the fetcher's helper library (APR overlays, campaign "
        "helpers, module-level ibkr constants like _ARCHIVE_TFS) is bound to IBKR "
        "mechanics; the overlays move leaf-owned or per-provider-plan-owned at the "
        "190-04 seam."
    ),
    "scripts/infrastructure/backfill/_history_fetch_item.py": (
        "SHRINKS IN 190-04: the IBKR item mechanics (qualification, FX/crypto "
        "derive, venue fallback) retreat into the leaf at the 190-04 seam; today "
        "it imports the module for the constants those mechanics read."
    ),
    "scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py": (
        "PERMANENT: the manual chunk-days/rate-limit calibration probe must drive "
        "the real IBKR leaf under FetcherLock to measure vendor pacing; concrete "
        "access is its purpose. It re-verifies the APR seeds after any limit change."
    ),
    "scripts/infrastructure/classification_ibkr_sourcing.py": (
        "PERMANENT (out of phase 190 scope): onboarding/classification sourcing "
        "qualifies candidate contracts on the concrete leaf during manifest runs; "
        "moves only if a protocol-level qualification seam is ever justified."
    ),
    "scripts/infrastructure/universe_expansion_onboard_manifest.py": (
        "PERMANENT (out of phase 190 scope): the onboarding manifest tool's dry run "
        "qualifies contracts on the concrete IBKR leaf (docs/foundation/"
        "instrument-onboarding-sop.md tooling); same rationale as classification "
        "sourcing."
    ),
    "scripts/infrastructure/universe_expansion_stratified_sourcing.py": (
        "PERMANENT (out of phase 190 scope): stratified universe sourcing resolves "
        "candidate contracts on the concrete IBKR leaf; same rationale as "
        "classification sourcing."
    ),
    "scripts/ops/bars/ops_d1_bootstrap.py": (
        "PERMANENT: manual IBKR ops tool (D1 capture bootstrap) run under "
        "FetcherLock against the concrete leaf; the manual ops tools keep concrete "
        "access until a reason to route them through the protocol exists."
    ),
    "scripts/ops/bars/ops_intraday_venue_recovery.py": (
        "PERMANENT: manual IBKR ops tool (intraday venue recovery) run under "
        "FetcherLock against the concrete leaf; same rationale as ops_d1_bootstrap."
    ),
    "scripts/ops/bars/ops_venue_study.py": (
        "PERMANENT: manual IBKR ops tool (D3 venue study) run under FetcherLock "
        "against the concrete leaf; same rationale as ops_d1_bootstrap."
    ),
    "services/backfill_feature_factory.py": (
        "PERMANENT (dormant DAG, unchanged this phase): the feature backfill "
        "service constructs IBKRProvider for its history reads; dormant since the "
        "v2.x archive and left byte-identical by phase 190."
    ),
}


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
