"""Drift tripwire: feature_edge_by_regime's WHERE clause vs the feature_lifecycle node's
cell query (todo 267; the query moved from ic_engine's retired hook to
services/feature_lifecycle.py's _CELLS_SQL in todo 402).

feature_edge_by_regime (migration 297) is deliberately matched to the row population
the feature lifecycle reads via SQL to decide concept_registry status -- two independently-maintained copies of the same business rule, no shared
source. If either one's SQL filter conditions change without the other being updated in
lockstep, the view silently drifts from what the hook actually reads -- the exact failure
shape CLAUDE.md's own gotchas doc calls out ("two independent incidents hit the same
shape of bug two weeks apart").

CI-clean: no DB, no network -- pure filesystem/regex over the two source locations. This
is a SQL-WHERE-clause tripwire only, not a full row-population proof: it fails loud if
either query's SQL predicates drift, but it cannot see (and does NOT cover) the hook's
Python-side post-filter -- the node additionally restricts to
`lookahead_bars == config.lookahead_mid[tf]` after the fetch (FeatureLifecycle.execute),
which `feature_edge_by_regime` does not apply (the view
exposes `lookahead_bars` as a plain unfiltered column instead, per migration 297's
"current vs history" convention) -- a real, currently-uncovered divergence between the
two, not verified or guarded by this test. It does not verify correctness of either
predicate from first principles.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_FEATURE_LIFECYCLE = _REPO_ROOT / "services" / "feature_lifecycle.py"
_MIGRATION_297 = _REPO_ROOT / "production" / "migrations" / "297_feature_edge_summary_views.sql"

# The lifecycle's own SQL predicate over feature_ic_scores (fis), normalized
# (table alias stripped, "!=" -> "<>", whitespace collapsed, lowercased) for comparison.
_HOOK_PREDICATES = {
    "symbol = 'pooled'",
    "is_pooled = true",
    "regime <> '_pooled'",
}

# feature_edge_by_regime's WHERE clause (migration 297) -- one extra condition
# (regime_scope = 'cross_sectional') that the migration's own comment documents as
# redundant given symbol = 'POOLED' (verified against the cross-sectional write site,
# not inferred from schema alone) -- kept in the view as defense-in-depth, not because
# the hook filters on it too.
_VIEW_PREDICATES = {
    "symbol = 'pooled'",
    "is_pooled = true",
    "regime_scope = 'cross_sectional'",
    "regime <> '_pooled'",
}


def _extract_where_predicates(sql_fragment: str) -> set[str]:
    """Split a `WHERE ... ` fragment's AND-joined conditions into a normalized set.

    Drops parameterized conditions (containing a placeholder, e.g. the lifecycle's own
    `training_window_end = $2`) -- those are per-call run-scoping, not part of the
    business-rule row population this test compares. The view exposes
    training_window_end as a plain column instead (per migration 297's own
    "current vs history" convention), so it has no equivalent condition to compare
    against.
    """
    match = re.search(r"WHERE\s+(.*)", sql_fragment, re.IGNORECASE | re.DOTALL)
    assert match, f"no WHERE clause found in:\n{sql_fragment}"
    clause = match.group(1)
    conditions = re.split(r"\bAND\b", clause, flags=re.IGNORECASE)
    normalized: set[str] = set()
    for cond in conditions:
        cond = cond.strip().rstrip(";").strip()
        if "%s" in cond or re.search(r"\$\d", cond):
            continue
        cond = re.sub(r"\bfis\.", "", cond)  # strip table alias
        cond = cond.replace("!=", "<>")
        cond = re.sub(r"\s+", " ", cond).lower()
        if cond:
            normalized.add(cond)
    return normalized


def _hook_where_fragment() -> str:
    text = _FEATURE_LIFECYCLE.read_text()
    def_idx = text.index("_CELLS_SQL = ")
    marker = "WHERE fis.symbol = 'POOLED'"
    start = text.index(marker, def_idx)
    end = text.index('"""', start)
    return text[start:end]


def _view_where_fragment() -> str:
    text = _MIGRATION_297.read_text()
    view_idx = text.index("CREATE OR REPLACE VIEW feature_edge_by_regime")
    end = text.index(";", view_idx)
    return text[view_idx:end]


def test_hook_filter_matches_recorded_predicates():
    """If this fails, feature_lifecycle's _CELLS_SQL filter changed -- update
    _HOOK_PREDICATES above AND check whether feature_edge_by_regime (migration 297)
    needs the matching change, per todo 267. Do not just silence this test."""
    assert _extract_where_predicates(_hook_where_fragment()) == _HOOK_PREDICATES


def test_view_filter_matches_recorded_predicates():
    """If this fails, feature_edge_by_regime's WHERE clause changed -- update
    _VIEW_PREDICATES above AND check whether feature_lifecycle's _CELLS_SQL
    needs the matching change, per todo 267. Do not just silence this test."""
    assert _extract_where_predicates(_view_where_fragment()) == _VIEW_PREDICATES


def test_hook_predicates_are_subset_of_view_predicates():
    """The tripwire itself, scoped to SQL WHERE-clause predicates only: the view's SQL
    filter must never be LOOSER than the hook's SQL filter (it may be stricter, per the
    documented-redundant regime_scope condition). This does NOT prove the view's full
    row population matches the hook's -- see this module's docstring for the known,
    uncovered lookahead_bars divergence (a Python-side post-filter this static test
    cannot see)."""
    assert _HOOK_PREDICATES <= _VIEW_PREDICATES
