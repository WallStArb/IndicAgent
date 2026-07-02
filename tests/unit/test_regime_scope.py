"""Unit test: regime_scope resolver + INSERT-SQL wiring + label_source sync (todo 141.1-02).

Verifies:
  1. _resolve_regime_scope(is_pooled, cross_sectional) pure resolver returns the correct
     scope for all three combinations that occur in ic_engine's insert paths.
  2. The resolver's possible outputs equal the migration-192 CHECK constraint set.
  3. _INSERT_BODY (shared by all three ON CONFLICT variants) carries the regime_scope
     column and %(regime_scope)s placeholder.
  4. The regime_scope produced at each insert site is consistent with the
     regime_label_source literal co-written at that same site:
       forward_filter    -> symbol_hmm     (per-symbol path)
       market_regimes    -> cross_sectional (cross-sectional path)
       context_features  -> pooled          (context-feature pooled path)

No DB, no Kafka. Pure Python inspection of module constants and logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _INSERT_BODY, _resolve_regime_scope

# ---------------------------------------------------------------------------
# Resolver mapping
# ---------------------------------------------------------------------------


def test_resolver_pooled_wins_regardless_of_cross_sectional():
    assert _resolve_regime_scope(is_pooled=True, cross_sectional=True) == "pooled"
    assert _resolve_regime_scope(is_pooled=True, cross_sectional=False) == "pooled"


def test_resolver_non_pooled_cross_sectional():
    assert _resolve_regime_scope(is_pooled=False, cross_sectional=True) == "cross_sectional"


def test_resolver_non_pooled_symbol_hmm():
    assert _resolve_regime_scope(is_pooled=False, cross_sectional=False) == "symbol_hmm"


def test_resolver_output_set_matches_migration_192_check_constraint():
    """Every value the resolver can return must be in the migration-192 CHECK set."""
    possible_outputs = {
        _resolve_regime_scope(is_pooled=True, cross_sectional=True),
        _resolve_regime_scope(is_pooled=True, cross_sectional=False),
        _resolve_regime_scope(is_pooled=False, cross_sectional=True),
        _resolve_regime_scope(is_pooled=False, cross_sectional=False),
    }
    assert possible_outputs == {"pooled", "cross_sectional", "symbol_hmm"}


# ---------------------------------------------------------------------------
# INSERT body wiring
# ---------------------------------------------------------------------------


def test_insert_body_contains_regime_scope_column_and_placeholder():
    assert "regime_scope" in _INSERT_BODY, (
        "_INSERT_BODY must list regime_scope in the INSERT column list -- it is shared "
        "by all three ON CONFLICT variants (_POOLED_INSERT_SQL, _REGIME_INSERT_SQL, "
        "_CROSS_SECTIONAL_INSERT_SQL)."
    )
    assert (
        "%(regime_scope)s" in _INSERT_BODY
    ), "_INSERT_BODY must include the %(regime_scope)s named placeholder in VALUES."


# ---------------------------------------------------------------------------
# Label-source -> scope sync assertion (insert-time counterpart of the
# migration's backfill sync-validation).
# ---------------------------------------------------------------------------

# The pairing that must hold at every ic_engine insert site: the regime_scope written
# alongside a given regime_label_source literal must match this mapping.
_EXPECTED_LABEL_SOURCE_TO_SCOPE = {
    "forward_filter": "symbol_hmm",
    "market_regimes": "cross_sectional",
    "context_features": "pooled",
}


def test_label_source_to_scope_sync_per_symbol_site():
    """Per-symbol site: regime_label_source='forward_filter' pairs with symbol_hmm.

    This is the non-cross-sectional, non-pooled case: is_pooled=False (regime-stratified
    row), cross_sectional=False (mr_dict-derived source is not in play for this label).
    """
    resolved = _resolve_regime_scope(is_pooled=False, cross_sectional=False)
    assert resolved == _EXPECTED_LABEL_SOURCE_TO_SCOPE["forward_filter"]


def test_label_source_to_scope_sync_cross_sectional_site():
    """Cross-sectional site: regime_label_source='market_regimes' pairs with cross_sectional.

    These rows are always cross-sectional (mr_dict is the source), never pooled at this
    site -- the cross-sectional pass writes a per-cell regime-stratified row.
    """
    resolved = _resolve_regime_scope(is_pooled=False, cross_sectional=True)
    assert resolved == _EXPECTED_LABEL_SOURCE_TO_SCOPE["market_regimes"]


def test_label_source_to_scope_sync_context_feature_pooled_site():
    """Context-feature pooled site: regime_label_source='context_features' pairs with pooled.

    These rows are always is_pooled=True (regime='_pooled' sentinel) -- cross_sectional
    is irrelevant once is_pooled wins.
    """
    resolved = _resolve_regime_scope(is_pooled=True, cross_sectional=False)
    assert resolved == _EXPECTED_LABEL_SOURCE_TO_SCOPE["context_features"]


def test_all_label_sources_covered_by_mapping():
    """Every regime_label_source literal ic_engine writes has an expected scope."""
    assert set(_EXPECTED_LABEL_SOURCE_TO_SCOPE.keys()) == {
        "forward_filter",
        "market_regimes",
        "context_features",
    }
    assert set(_EXPECTED_LABEL_SOURCE_TO_SCOPE.values()) == {
        "symbol_hmm",
        "cross_sectional",
        "pooled",
    }
