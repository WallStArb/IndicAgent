---
status: pending
priority: P1
filed: 2026-07-23
source: Phase 163 (VP/SR Structural Primitives) execution -- discovered mid-phase while
  executing Wave 3, confirmed against live persistence code before filing
gate: Phase 163 fully executed (all 3 waves) -- this todo is the operational follow-up,
  not part of the phase's own plans
decision: Delete + full recompute (option a), confirmed 2026-07-23. Full 58-symbol/multi-tf/
  multi-year corpus is in scope unless a narrower window is confirmed sufficient at run time.
---

# feature_vectors' 17 new VP/SR columns are NULL on every pre-existing row -- need a targeted historical backfill, not a naive re-run

## Context

Phase 163 (migration 255) added 17 new `feature_vectors` columns (12 ATR-normalized VP fields
per D-16/D-17/D-18, 5 S/R strength/age/count fields per D-19) and wired `FeatureFactory.compute()`
(live) / `compute_batch()` (backfill) to populate them going forward. This makes new bars correct
from the moment 163 ships. It does **not** touch the existing historical corpus -- every
`feature_vectors` row written before migration 255 has NULL in all 17 new columns and will stay
NULL forever unless something explicitly backfills them.

**Confirmed blocker (not theoretical):** `FEATURE_VECTOR_INSERT_SQL`
(`src/intelligence/features/feature_vector_persistence.py:157`) uses
`ON CONFLICT (...) DO NOTHING` -- the module's own comment says "idempotent replay; duplicate
bars are skipped silently." A naive re-run of
`scripts/... backfill_feature_factory.py --compute-only` over the historical date range will
silently no-op on every `(symbol, tf, bar_ts)` that already has a row -- which is the entire
existing corpus. The new columns will NOT get backfilled by just re-running the existing script
as-is.

**Why this matters now, not eventually:** Phase 166's structural candidate was correctly halted
specifically because `sr_support_dist`/`sr_resist_dist` were 100% NULL in the historical corpus
(the reason Phase 163 was promoted to a Wave-0 prerequisite in the first place). Phase 163 wiring
the live compute path is necessary but not sufficient -- Phase 166 Part 2 (rescoring the
structural candidate through gate166, tracked in todo 175) needs real historical VP/SR values
across the IN-SAMPLE and OOS corpus, not just new bars accumulating from today forward. Without
this backfill, todo 175 / Phase 166 Part 2 will hit the exact same 100%-NULL wall Phase 166 Part 1
already hit.

## What needs to happen

**Decision (2026-07-23): delete + full recompute (option a).** DELETE the affected historical
`feature_vectors` rows, then re-run `backfill_feature_factory.py --compute-only` over them. This
recomputes all ~181 columns (not just the 17 new ones) but reuses existing, already-reviewed
code as-is rather than building and reviewing a new targeted UPDATE-only path. Full corpus is the
default scope -- narrow to the in-sample + OOS window only if the full-corpus cost proves
prohibitive at run time.

1. Confirm the exact affected row set before deleting: every `feature_vectors` row with
   `bar_ts`/insert time before migration 255 landed (or more simply, every row where all 17 new
   columns are NULL -- cheaper to verify, same result if the columns are truly untouched
   pre-migration).
2. DELETE those rows, then run `backfill_feature_factory.py --compute-only` (full corpus unless
   scope is narrowed per above) to regenerate them with the new columns populated.
3. Verify via a spot-check that `sr_support_dist`/`poc_dist_atr`/etc. are non-NULL and
   non-constant across a sample of recomputed rows (mirror the "non-constant" regression guard
   Phase 163 Plan 02 added for the live path).
4. Confirm `ic_engine`'s corpus fingerprinting (Phase 162) correctly detects the recomputed rows
   as a fingerprint change and doesn't silently skip recompute for affected cells.
5. `feature_vectors` is a live-read table (ic_engine, AlphaFrameWriter's structural candidate) --
   confirm no consumer reads it mid-DELETE/recompute window, or run during a window where that's
   acceptable (matches the "briefly leaves feature_vectors short rows mid-run" risk noted for
   this option).

## Acceptance criteria

- [x] Backfill mechanism chosen (delete + full recompute, 2026-07-23)
- [ ] Historical `feature_vectors` rows (scope per above) have non-NULL, non-constant values in
      all 17 new VP/SR columns
- [ ] `ic_engine` corpus fingerprint correctly triggers recompute for cells whose feature values
      changed as a result of this backfill
- [ ] Documented which date range / symbol set was actually backfilled, for todo 175's future
      reference
