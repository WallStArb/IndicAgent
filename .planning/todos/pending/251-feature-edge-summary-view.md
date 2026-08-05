---
status: pending
priority: P1
filed: 2026-08-04
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
