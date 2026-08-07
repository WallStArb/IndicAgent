---
status: pending
priority: P3
filed: 2026-08-05
source: altitude review (/simplify) of todo 251's feature_edge_by_regime/feature_edge_by_symbol
  views (migration 297)
---

# `feature_edge_by_regime`'s WHERE clause duplicates `_apply_feature_transitions`' live filter logic with no drift tracking

## What

`feature_edge_by_regime` (migration 297) filters
`symbol = 'POOLED' AND is_pooled = true AND regime_scope = 'cross_sectional' AND regime <> '_pooled'`
-- deliberately matched to the exact population `services/ic_engine.py`'s own
promotion/demotion lifecycle hook (`_apply_feature_transitions`, ~line 4467-4485) reads to
decide `feature_registry` status. This is a real "two independently-maintained copies of one
business rule" shape -- the failure class CLAUDE.md's own gotchas doc calls out ("two
independent incidents hit the same shape of bug two weeks apart").

If `_apply_feature_transitions`' query ever changes (a new `regime_scope` value, a sentinel
rename, an additional filter condition), nothing forces `feature_edge_by_regime` to update in
lockstep -- the view would silently start misrepresenting what the hook actually promotes on,
undermining its whole purpose as an audit surface for "what does the system currently believe
has edge."

## Why not fixed as part of todo 251

A deeper fix (the hook reads the view instead of its own inline SQL, making the view the single
source of truth) is not a same-scope refactor: the hook's query also `LEFT JOIN`s
`ensemble_weights` for `standing_weight` and pins `lookahead_bars` in Python against
`config.lookahead_mid[tf]`, neither of which the view does. Making the view the hook's actual
source of truth means either rewriting a live promotion/demotion decision path to consume a
reporting view, or growing the view to carry ensemble-weight joins it doesn't conceptually
need -- both bigger, riskier changes than "add a reporting view."

## Also: two operational follow-ups noted by the efficiency review, not migration-file changes

`feature_ic_scores` was empty at migration-297-review time (corpus recompute pending, todo 259),
so query-plan behavior was verified against stale/absent statistics rather than real data:
1. For `feature_edge_by_symbol`, the planner chose the general `training_window_end` index over
   the more selective partial `feature_ic_scores_pooled_uq` index (its twin query,
   `feature_edge_by_regime`, DID use the matching partial index). Plan-cost noise on an empty
   table, not a confirmed regression -- but worth a real `EXPLAIN ANALYZE` check once real data
   exists.
2. Run `ANALYZE feature_ic_scores` after the corpus recompute lands (fresh statistics), then
   re-`EXPLAIN` both views' "current edge" query pattern
   (`WHERE training_window_end = (SELECT max(training_window_end) FROM feature_ic_scores)`) to
   confirm chunk-pruning and partial-index selection still hold at real row counts.

## Fix

Either:
- File a lighter-weight tripwire: a unit/integration test that asserts `_apply_feature_transitions`'
  SQL filter and `feature_edge_by_regime`'s view definition agree on the same row population
  (e.g. compare `EXPLAIN`-derived predicates, or run both queries against a seeded fixture and
  assert identical row sets) -- fails loud if they ever drift, without requiring either to
  change today.
- Or, if `_apply_feature_transitions` is ever refactored for other reasons, evaluate at that
  time whether it should read `feature_edge_by_regime` directly (minus the ensemble-weight join,
  applied as a separate step) rather than maintaining its own inline SQL.

Whichever direction: also complete the two operational checks above (post-recompute
`ANALYZE` + `EXPLAIN ANALYZE` re-verification) in the same pass.

## Tripwire landed 2026-08-07

Took the lighter-weight option: `tests/unit/test_feature_edge_by_regime_filter_parity.py`,
CI-clean (no DB, pure filesystem/regex over `services/ic_engine.py` and
`production/migrations/297_feature_edge_summary_views.sql`). Extracts both WHERE clauses'
AND-joined conditions into normalized sets and asserts (1) the hook's filter still matches a
recorded baseline, (2) the view's filter still matches a recorded baseline, (3) the hook's
predicate set is a subset of the view's -- so the view can never be looser than what the hook
actually promotes/demotes on. Parameterized conditions (the hook's own
`training_window_end = %s`) are excluded from comparison -- that's per-call run-scoping, not
part of the business-rule population, and the view exposes it as a plain column instead.
Verified the test actually catches drift: it failed as expected before this exclusion was
added (correctly flagged `training_window_end = %s` as an unrecognized hook condition), which
is direct evidence the extraction logic is sensitive to real differences, not just green by
construction.

**Still open, not done in this pass** (deliberately -- both need real corpus data, which
doesn't exist yet pending todo 243's recompute): the two operational follow-ups --
`ANALYZE feature_ic_scores` + re-`EXPLAIN ANALYZE` both views' "current edge" query pattern
once the corpus recompute lands. Re-check this todo once todo 243 closes.
