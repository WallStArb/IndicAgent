---
status: pending
priority: P3
filed: 2026-09-23
source: 233/255 compute_eligible reconciliation during Phase 176 execution, 2026-09-23
---

# The `compute_1d` eligibility dimension has no consumer: the 40 Phase 174 pilot names were never featurized, and their 1d OHLCV stopped updating

## What

Migration 341 (Phase 174) added `instruments.compute_eligible_1d`, and `get_active_contracts()`
maps `dimension="compute_1d"` to `is_active = true AND compute_eligible_1d = true`
(`src/config/settings.py:387`). Nothing reads that dimension:

- `services/backfill_feature_factory.py` and the live pipeline use the default `compute`
  dimension, so the 40 pilot names (`compute_eligible=false`, `compute_eligible_1d=true`) have
  **zero `feature_vectors` rows**, not even at 1d.
- `infrastructure_nightly_backfill.py` also uses `compute`, so their 1d OHLCV has not been
  refreshed since the one-shot pilot fetch: `MAX(timestamp)` is 2026-09-15 for all 40, the same
  day as the fetch.
- `infrastructure_run_historical_pipeline.py --dimension compute_1d` exists but is manual.

The Phase 174 verdict doc (`docs/research/phase174-down-cap-correlation-gate-verdict.md`,
"Corpus retention") keeps these 40 as a "measurement asset" with "real 1d history". The history
exists, but it is not growing and has no features, so no IC-based construction can use it today.

## Reconciliation (for the record)

`compute_eligible` = 255 = the 233 symbols present in `feature_vectors` + 22 inactive
(`is_active=false`) instruments whose `compute_eligible` flag is still `true` while holding zero
tradeable bars. That flag is stale and should be set to false on those 22 in the same change, so
the count stops reading as a gap.

## Fix

1. Decide whether the pilot cohort stays a live measurement asset (then: nightly 1d refresh via
   `dimension="compute_1d"` and a 1d-only feature backfill pass), or a frozen snapshot (then:
   state that in the verdict doc and stop calling it growing history).
2. Clear the stale `compute_eligible` flag on the 22 inactive instruments via a migration with a
   `reason`.

## Gate

None. Not on 176-08's path: 176-07's COVERED_SCOPE is derived from `feature_vectors`, so these
40 are correctly out of scope for that verdict.

## Triage 2026-09-26 (backlog review with the owner)

Closed: premise gone. The research snapshot reads `compute_eligible_1d` (931 names); stale compute_eligible flags on inactive instruments = 0 (checked 2026-09-26).
