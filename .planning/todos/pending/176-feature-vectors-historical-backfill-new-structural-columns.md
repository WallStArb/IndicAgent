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

**Superseded 2026-07-27: mechanism now exists, decision below is stale.** The original
2026-07-23 decision (delete + full recompute) is no longer the plan -- while investigating why
`feature_vectors` was found 20 days stale (separate session finding), the actual root cause of
*this* todo's blocker was traced precisely: `FEATURE_VECTOR_INSERT_SQL`'s
`ON CONFLICT (symbol, tf, bar_ts) DO NOTHING` is keyed on the table's real PRIMARY KEY
(`(symbol, tf, bar_ts)`, not `feature_vector_id`), so it can never overwrite an existing row no
matter what changed. Fixed at the source: `feature_vector_persistence.py` now also exports
`FEATURE_VECTOR_UPSERT_SQL`/`FEATURE_VECTOR_UPSERT_SQL_PSYCOPG2` (`DO UPDATE SET` every non-PK
column, generated from the same single column-list as the INSERT variant so they can't drift
apart), and `backfill_feature_factory.py` gained a `--refresh` flag that selects it and also
bypasses the `backfill_status.status='complete'` checkpoint skip. **This avoids the DELETE step
entirely** -- no "briefly leaves feature_vectors short rows mid-run" risk window, since rows are
updated in place rather than deleted-then-reinserted. The live write path (`feature_vector_writer.py`)
is untouched -- still `DO NOTHING`, so a replayed live bar stays a no-op. Verified bit-identical
equivalence on a separate refactor in the same session (see `compute_batch()`'s window-slicing
fix); the upsert SQL itself is structurally tested
(`tests/unit/test_feature_vector_persistence_completeness.py`,
`tests/unit/services/test_backfill_feature_factory.py`).

**Revised steps:**

1. Run `backfill_feature_factory.py --compute-only --refresh` (full corpus unless scope is
   narrowed at run time). No DELETE step needed.
2. Verify via a spot-check that `sr_support_dist`/`poc_dist_atr`/etc. are non-NULL and
   non-constant across a sample of recomputed rows (mirror the "non-constant" regression guard
   Phase 163 Plan 02 added for the live path).
3. Confirm `ic_engine`'s corpus fingerprinting (Phase 162) correctly detects the recomputed rows
   as a fingerprint change and doesn't silently skip recompute for affected cells.
4. Document which date range / symbol set was actually backfilled, for todo 175's future
   reference.

**Not yet run** -- this todo tracks the mechanism now existing, not the actual recompute having
happened. `feature_vectors` was also found 20 days stale overall (unrelated root cause -- live
ingestion is intentionally paused, see `[[project_ingestion_intentionally_paused]]`), so the
`--refresh` run doubles as closing that gap too, in one pass.

## Acceptance criteria

- [x] Backfill mechanism chosen (delete + full recompute, 2026-07-23)
- [ ] Historical `feature_vectors` rows (scope per above) have non-NULL, non-constant values in
      all 17 new VP/SR columns
- [ ] `ic_engine` corpus fingerprint correctly triggers recompute for cells whose feature values
      changed as a result of this backfill
- [ ] Documented which date range / symbol set was actually backfilled, for todo 175's future
      reference
