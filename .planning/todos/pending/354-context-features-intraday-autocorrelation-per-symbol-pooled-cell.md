---
status: pending
priority: P0
filed: 2026-08-25
source: Phase 173 Plan 02 (173-02-PLAN.md Task 2) -- surfaced while deleting ic_engine.py's
  bespoke CONTEXT_FEATURES daily-cadence significance path
---

# vix_z/yield_slope_z/flight_quality now measured only via per-symbol intraday duplication --
# temporal pseudo-replication, a different bug than the one Phase 173 fixes

## What

Phase 173 Plan 02 deleted `ic_engine.py`'s bespoke daily-cadence significance path for
`vix_z`/`yield_slope_z`/`flight_quality` (the `CONTEXT_FEATURES` frozenset and its
`context_features`-table query inside `_compute_symbol_tf`). Before the deletion, that path
existed specifically to avoid measuring these three macro features from `feature_vectors`
directly, because doing so means one daily value gets duplicated across every intraday bar of
that day -- ~78x at 5m, ~26x at 15m, ~6.5x at 1h. The deleted block's own comment documented
this exact reason for its existence:

> Measuring IC from feature_vectors would inflate IC via artificial autocorrelation (same daily
> value duplicated ~78 times for 5m TF).

**Pre-deletion gate result (proves the deletion itself dropped no live measurement):** a live
query run immediately before the deletion (2026-08-25T16:02:30Z) returned
`SELECT count(*) FROM feature_ic_scores WHERE regime_label_source='context_features'` = **0**.
The daily-cadence path had zero live rows at deletion time -- this todo is not about lost data,
it is about the code path these three features now fall back to.

With the daily-cadence path gone, `vix_z`/`yield_slope_z`/`flight_quality` are measured
**only** through `_compute_symbol_tf`'s ordinary intraday per-symbol path (reading the columns
directly off `feature_vectors`, same as any per-symbol-varying feature). That path has no
daily-deduplication step -- it treats each intraday bar as an independent observation of
whatever value `feature_vectors` carries for that bar, which for these three columns is the
same value repeated for every bar of the trading day. This inflates effective N by the same
duplication factor the deleted comment warned about, in the per-symbol pooled cell.

## Why this is a DIFFERENT bug than the one Phase 173 fixes

Phase 173's own broadcast-cell mechanism (Plans 03/04) fixes **cross-sectional pseudo-
replication** -- independence assumed across SYMBOLS at a single `bar_ts`, when a broadcast
feature's value is identical across every symbol in the pool. That fix builds a dedicated
broadcast cell against an equal-weighted market-aggregate return, explicitly for the
cross-sectional path (`_compute_cross_sectional_tf` / `_compute_one_cross_sectional_cell`).

This todo is **temporal pseudo-replication** -- independence assumed across BARS within a
single symbol's own intraday time series, when the feature's value is constant across every
bar of a trading day. It lives in the per-symbol pooled path (`_compute_symbol_tf`), a
different cell, a different axis of non-independence. **The Phase 173 broadcast cell does NOT
cover this path.** Fixing cross-sectional pseudo-replication does nothing for temporal
pseudo-replication in the per-symbol cell; they are orthogonal bugs that happen to share the
same three feature names as their most visible instance.

## Proposed fix (not implemented here)

A temporal-decimation stride for broadcast features specifically inside the per-symbol pooled
cell -- analogous to the existing `subsample_min_stride` mechanism (`alpha.ic.subsample_min_stride`
APR key, `services/ic_engine.py`), which already exists to counter a related (but not identical)
over-counting problem for ordinary per-symbol features. The natural shape: detect
broadcast-classified features (via `concept_registry.metadata->>'broadcast'`, the same
classification source Phase 173's cross-sectional fix reads) inside `_compute_symbol_tf`, and
for those features only, subsample to roughly one observation per calendar day rather than the
feature's own native `subsample_min_stride` bar-count stride -- mirroring the deleted
daily-cadence path's `DISTINCT ON (DATE(bar_ts))` logic, but sourced from `feature_vectors`
directly instead of a separate `context_features` table.

## Scope

Not fixed by this todo's filing, and not in scope for Phase 173 (confirmed via Plan 02's own
`must_haves` truths -- deletion was gated on proving zero rows lost, not on immediately
replacing the deleted mechanism with an equivalent one). File for future prioritization.
