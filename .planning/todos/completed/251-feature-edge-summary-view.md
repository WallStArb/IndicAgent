---
status: partially-fixed
priority: P1
filed: 2026-08-04
fixed: 2026-08-05
source: conversation working through "where do we go to see what has edge" -- concluded
  feature_ic_scores already has everything needed (training_window_end is the walk-forward
  time axis, history accrues automatically as new corpus runs land), the only real gap is a
  query to collapse the granularity into something readable. Supersedes the abandoned
  ops_primitive_discovery_report.py skeleton (Phase 142.5 Plan 00), which tried to answer the
  same question with a full report-generator script instead of a plain view.
---

# Create a `feature_ic_scores` edge-summary view (current + history) -- delete the orphaned discovery-report skeleton

## What

No consolidated place exists to answer "which features currently show edge" or "how has a
feature's edge trended over corpus runs." `feature_ic_scores` already has both answers built
in -- it just isn't queried that way today:

- **Current edge**: `symbol = 'POOLED' AND is_pooled = true AND regime_scope = 'cross_sectional'`
  gives the pooled-across-symbols, per-regime cells -- the same population the ic_engine
  lifecycle hook itself evaluates. Gate on `passes_fdr` / `passes_walkforward`, rank by
  `ic_sharpe` / `ic_ci_lower`.
- **History**: `training_window_end` is the walk-forward data boundary, not a run timestamp --
  each new corpus run appends a new value as its cutoff advances, so a plain
  `ORDER BY feature_name, tf, regime, training_window_end` is already the trend line. There is
  currently only one `training_window_end` (2025-12-24, computed 2026-07-30) because there has
  been exactly one corpus run since this schema existed -- not a staleness problem, just not
  enough history yet. No new write path or table is needed for this to start working; it
  accrues automatically as the corpus pipeline reruns.

Two grains exist and should probably both get a view (don't collapse them into one number --
that would hide regime-conditional edge, which the segment-by-regime principle explicitly
wants preserved):
1. `feature_edge_by_regime` -- cross_sectional POOLED, per (feature, tf, regime, lookahead_bars).
2. Optionally `feature_edge_by_symbol` -- `regime_scope='pooled'`, per (feature, symbol, tf,
   lookahead_bars) -- pooled across regime, split by symbol, the other existing pooling axis.

## Also: retire the orphaned skeleton

`scripts/analysis/ops_primitive_discovery_report.py` (Phase 142.5 Plan 00) is an unimplemented
skeleton (`generate_primitive_discovery_report()` / `_write_report()` both `raise
NotImplementedError`) that was scoped to answer this same question via a full markdown
report generator. Once the view above exists, decide whether to finish that script on top of
it (if a periodic markdown artifact is still wanted) or delete it outright as superseded
scaffolding -- don't leave both a view and a half-built report generator as parallel unfinished
answers to the same question.

## Notes

- Not blocked on todo 250 (feature_ic_scores hypertable/retention) -- the view works against
  the table as-is regardless of partitioning status. Sequence independently.
- Not blocked on todo 118 (concept registry migration) -- this reads feature_ic_scores directly,
  never feature_registry or concept_registry. Keep it that way (measurement layer stays the
  source for reporting; governance layer stays actuator-only, per the 2026-08-04 architecture
  review's measurement/governance/reporting split).

## Fix applied 2026-08-05 (migration 297) -- views done, skeleton retirement deferred

**Done:** `feature_edge_by_regime` and `feature_edge_by_symbol` views created (migration 297),
matching the two grains this todo specified exactly. Filters were verified against
`services/ic_engine.py`'s actual live write/read paths, not taken from this todo's own prose
(which described one unreachable filter combination) -- full derivation trail is in migration
297's own header comment, not repeated here. Verified both views against live synthetic rows
covering all 3 `regime_scope` values (cross_sectional/pooled/symbol_hmm) -- each row landed in
exactly the view it belonged to, `symbol_hmm` rows in neither (correct, no view covers that
grain yet -- not asked for by this todo).

**Deferred, not done:** retiring `scripts/analysis/ops_primitive_discovery_report.py` (the
orphaned skeleton this view supersedes). Phase 170 (feature_registry -> Concept Registry
migration) is running in a separate, concurrent session as of 2026-08-04 per `.planning/STATE.md`,
and its most recent commit (`fb638e86`) already swept a comment-only reference through this exact
file. Deleting or modifying it now risks a real conflict with that session's in-flight work --
confirmed via `git log -- scripts/analysis/ops_primitive_discovery_report.py`, not assumed.
Re-open this decision (finish the report generator on top of the new views, or delete the
skeleton outright as superseded scaffolding, per this todo's original framing) once Phase 170
merges to `main`.

## CLOSED 2026-08-21

Phase 170 merged 2026-08-10 (migration 311). Decision: delete, not finish. The skeleton was
`raise NotImplementedError` in both its would-be query and report-writing functions -- zero real
logic to preserve -- and `feature_edge_by_regime`/`feature_edge_by_symbol` already provide
directly-queryable reporting, making a separate markdown-report generator redundant complexity,
not a missing capability. Confirmed no live caller before deleting (`grep -rn
ops_primitive_discovery_report`): only self-references (own docstring/help text), a
`tools/vulture_whitelist.py` dead-code allowlist (8 entries, cleaned up alongside), and a
comment-only mention in `tests/unit/services/test_ic_engine.py` (no import, updated to cite the
views instead). Full `tests/unit/` green, vulture/ruff/black clean.
