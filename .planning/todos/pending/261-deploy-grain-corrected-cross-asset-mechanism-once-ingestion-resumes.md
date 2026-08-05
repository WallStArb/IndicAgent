---
status: pending
priority: P1
found_during: phase-151-plan-09
found_date: 2026-08-05
---

# Deploy Plan 151-09's grain-corrected live cross-asset mechanism once IBKR ingestion resumes

## What

Plan 151-09 replaced `FeatureVectorPipeline`'s live cross-asset mechanism (todo 221/222's
per-timeframe `CrossAssetState`) with a daily-grain mechanism that calls the SAME
`build_cross_asset_series()` the batch/corpus path calls, correcting a confirmed grain
mismatch (see 151-09-SUMMARY.md's Grain Mismatch Finding, and this todo's References). The
code change (`services/feature_vector_pipeline.py`, `src/intelligence/features/
cross_asset_series.py`) is complete, unit-tested, and merged to main. It has **not been
deployed to the live `indicagent-feature-vector-pipeline` daemon**, and Plan 151-09's own
Task 3 (restart + verify newly-written rows carry correct, non-zero, grain-correct values)
was **not executed**.

## Why deployment was deferred, not just "not yet gotten to"

Two independent reasons, either alone sufficient to defer:

1. **Live IBKR ingestion is intentionally paused** (confirmed 2026-07-27, unrelated to this
   plan -- see `project_ingestion_intentionally_paused` in memory). `SELECT max(bar_ts) FROM
   feature_vectors WHERE tf='5m'` returned `2026-07-28` when checked 2026-08-05 -- an 8-day-
   stale corpus. Restarting the daemon right now would produce **zero new bars regardless**,
   so Plan 151-09's Task 3 verification (newly-written rows are non-zero / grain-correct) is
   structurally impossible to run today, not merely inconvenient.
2. **This is a full mechanism replacement, not an additive extension.** The change removes a
   previously-shipped, currently-running live mechanism (`CrossAssetState`/
   `_refresh_cross_asset_state`/`_warm_cross_asset_state`/`_get_cross_asset_state`/
   `_cross_asset_state_for_bar`, todo 221/222, landed 2026-07-31) and replaces it with a new
   design (daily 1d-bar DB fetch at setup + once-per-UTC-day refresh + causal "most recent
   <= d" broadcast). It is unit-tested against synthetic data but has never run against the
   live DB's real SPY/TLT/SHY/TIP/HYG/LQD history or under real bar-arrival timing. Restarting
   a currently-`active` production daemon with this rewrite, unattended, without an operator
   able to watch the restart and roll back if `_setup()`'s cross-asset load misbehaves in a
   way the try/except doesn't anticipate, is not a call an executor session should make
   unilaterally.

## What to do when ingestion resumes (or an operator wants to verify sooner)

Run Plan 151-09's Task 3 exactly as written (`.planning/phases/151-feature-primitives-
expansion-theory-motivated-interaction-la/151-09-PLAN.md`'s Task 3 section), adapted for the
new mechanism:

1. Record the pre-restart baseline (`vix_z = 0.0` zero-counts, `max(bar_ts)`).
2. `sudo systemctl restart indicagent-feature-vector-pipeline`; confirm `active`; check
   `logs/feature_vector_pipeline.log` for the one-time `cross_asset.series_refreshed` line at
   setup and zero `cross_asset.series_load_failed` warnings.
3. Once genuinely new bars exist (requires ingestion active + market hours), assert
   `vix_z = 0.0` count is 0 for rows strictly newer than the pre-restart `max(bar_ts)` (or the
   exceptions are named and explained).
4. Cross-check one symbol's live values against the batch-computed value for the same
   trading day (same daily-grain builder now on both paths, so they should match closely,
   modulo the live daemon's z-score windows warming up from a shorter buffered-bar-history
   replay than the batch path's full corpus).
5. Also spot-check the 5 NEW fields (`tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast/slow/z`)
   are non-zero on newly-written rows -- Plan 151-09 extended coverage to these for the first
   time on the live path; the old mechanism never touched them at all.

## References

- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-SUMMARY.md` -- full grain-mismatch finding, evidence trail, and design rationale
- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-PLAN.md` -- Task 3's original restart/verify procedure (still the right shape, just re-run against the new mechanism)
- `services/feature_vector_pipeline.py` -- `_load_cross_asset_series`/`_cross_asset_record_for_date`/`_refresh_cross_asset_series`
- `src/intelligence/features/cross_asset_series.py` -- `build_cross_asset_series` (the shared builder both paths now call)
- `project_ingestion_intentionally_paused` (memory) -- why ingestion is off and not an outage to root-cause
