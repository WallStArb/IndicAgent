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
