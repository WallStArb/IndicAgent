---
phase: 163-vp-sr-structural-primitives
plan: 01
subsystem: database
tags: [timescaledb, feature-factory, apr, volume-profile, feature-vectors, config-service]

# Dependency graph
requires: []
provides:
  - "17 new feature_vectors columns (12 ATR-normalized VP + 5 S/R strength/age/count) + matching feature_registry rows, backing todo 153"
  - "FeatureVector dataclass, FEATURE_VECTOR_DOMAIN, and feature_vector_persistence.py INSERT contract extended to 181 columns"
  - "feature.session_vp.* / feature.sr.* APR namespace (8 keys) + FeatureFactoryConfig fields"
  - "FeatureCache.update_session_vp() mutator: session-anchored, non-incremental volume-weighted histogram (POC/VAH/VAL/HVN/LVN raw levels), ready for Plan 02 to wire into compute paths"
affects: [163-02, 163-03, 166]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Derive-by-name field slice for persistence (_STRUCTURAL_VP_SR_FIELD_NAMES), same discipline as _RENAISSANCE_PRIMITIVE_FIELD_NAMES/_CANARY_FIELD_NAMES"
    - "Session-boundary-reset accumulator keyed on ET calendar date derived via _et_from_utc + the existing ny_start_utc_hour/minute APR key (update_wk_vwap's ISO-week-reset pattern, generalized)"
    - "Non-incremental per-call histogram recompute (avoids market_profile.py's D-01 unbounded-accumulator bug)"

key-files:
  created:
    - production/migrations/255_vp_structural_primitives.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/feature_cache.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/test_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/test_canary_predictors.py

key-decisions:
  - "Migration renumbered 243 -> 255: 243 was already claimed by a concurrent session (todo 162's fix, merged before this plan executed); 255 is the verified next-free number"
  - "New feature_vectors columns use double precision, not the plan's stated real (float32): live schema inspection shows migration 201's float32 conversion only touched the 156 columns it explicitly listed; every column added since (migrations 197/216) is double precision, so this migration matches the actual live convention"
  - "feature_registry INSERT uses the real live schema (group_name/tier/formula_short/normalization/linear_ready/requires_htf/status/added_phase), not the plan's stated is_bounded/is_directional column pair, which does not exist in the live table"
  - "S/R comparable-scalar/count fields (resistance_strength/support_strength/resistance_age_bars/support_age_bars/sr_level_count) use normalization='unbounded_ratio' (matches vol_ratio/garch_ratio precedent), not the plan's stated 'none', which has zero precedent in the live table"

requirements-completed: ["TODO-153", "D-03", "D-06", "D-13", "D-16", "D-19"]

# Metrics
duration: ~45min
completed: 2026-07-23
---

# Phase 163 Plan 01: VP/SR Structural Primitives Data Contract Summary

**17 new ATR-normalized/bounded feature_vectors columns (12 volume-profile + 5 support/resistance) end-to-end through schema, feature_registry, FeatureVector dataclass, and persistence INSERT, plus a working session-volume-profile histogram mutator on FeatureCache — ready for Plan 02 to wire real computation into the live/backfill compute paths.**

## Performance

- **Duration:** ~45 min (research + 2 tasks; exact start not captured, task commits span 12:31–12:44 local)
- **Completed:** 2026-07-23
- **Tasks:** 2/2 completed
- **Files modified:** 16 (1 created, 15 modified)

## Accomplishments

- Migration 255 adds 17 real, ATR-normalized/bounded `feature_vectors` columns (no raw price levels), 17 matching `feature_registry` rows, and 8 new `feature.session_vp.*`/`feature.sr.*` APR keys — closing the schema half of todo 153
- `FeatureVector` dataclass, `FEATURE_VECTOR_DOMAIN`, and `feature_vector_persistence.py`'s INSERT contract stay perfectly in sync (verified live: registry name-set == dataclass field-set, 172 fields; ic_engine's crash-loud drift gate would pass)
- `FeatureCache.update_session_vp()` computes real session POC/VAH/VAL/HVN/LVN raw levels from a session-boundary-reset bar accumulator, ported from `ctx_VolumeProfile` — verified against a synthetic 40-bar round-trip session (VAH >= POC >= VAL holds, session resets correctly at the next day's 9:30 ET open)
- Found and fixed a real correctness bug in the ported value-area algorithm during verification (see Deviations)

## Task Commits

1. **Task 1: Migration 255 + FeatureVector/domain/persistence contract for 17 new structural columns** - `4dc708f4` (feat)
2. **Task 2: FeatureFactoryConfig VP/SR fields + FeatureCache.update_session_vp() mutator** - `0ff48698` (feat)

## Files Created/Modified

- `production/migrations/255_vp_structural_primitives.sql` - 17 `feature_vectors` columns + 17 `feature_registry` rows + 8 APR keys
- `src/intelligence/schemas.py` - `FeatureVector` dataclass: 17 new session-level fields, D-05 stale comment corrected
- `src/intelligence/feature_factory.py` - `FEATURE_VECTOR_DOMAIN` (17 new `"structural"` entries), `FeatureFactoryConfig` (8 new defaulted VP/SR fields), `_build_feature_vector`/`_cold_start_vector` updated for the new required fields
- `src/intelligence/feature_cache.py` - `update_session_vp()` mutator, internal `_sess_*` raw-level state, ported `_compute_session_vp_profile`/`_compute_session_value_area`/`_compute_session_directional_nodes` helpers (with a tie-break bug fix)
- `src/intelligence/features/feature_vector_persistence.py` - `_STRUCTURAL_VP_SR_FIELD_NAMES` derived slice, INSERT SQL/params extended to 181 columns
- `services/feature_vector_pipeline.py` - `_THRESHOLD_KEYS` + `_prewarm_threshold_config()` wired for the 8 new APR keys
- `services/backfill_feature_factory.py` - `_build_feature_factory_config()` wired for the 8 new APR keys, `_sr_lookback_by_tf_from_config()` helper
- 6 test files - updated hardcoded `FeatureVector(...)` constructions and stale field/column-count assertions (150/155/164 → 172/181) that broke as a direct consequence of Task 1's new required dataclass fields

## Decisions Made

- **Migration renumbering (243 → 255):** the plan's own text named the file `243_vp_structural_primitives.sql`, but migration 243 was already claimed by a concurrent session (todo 162's `alpha.frame.min_stop_price_fraction` fix, merged to `main` before this phase executed) and the sequence has since advanced through 254 (Phase 166). Used 255, the verified next-free number — same collision class as migration 216's own documented numbering note.
- **Column type: `double precision`, not `real`:** the plan cited migration 201's float64→float32 conversion, but live schema inspection shows that migration only converted the 156 columns it explicitly listed — every column added afterward (migrations 197, 216) is `double precision`, and zero `real` columns exist in the live table today. Matched the actual live convention for consistency.
- **feature_registry schema: real columns, not the plan's imagined ones:** the plan described an `is_bounded`/`is_directional` column pair matching a stale draft of migration 169's schema. The live table (`\d feature_registry`) has no such columns — real columns are `feature_name`/`group_name`/`tier`/`formula_short`/`normalization`/`linear_ready`/`requires_htf`/`status`/`added_phase` (plus later governance columns). Inserted against the real schema.
- **S/R normalization value: `unbounded_ratio`, not `none`:** the plan specified `normalization='none'` for the 5 comparable-scalar/count S/R fields, but `'none'` has zero precedent anywhere in the live table (existing values: `z_scored`/`bounded_signed`/`bounded_unsigned`/`unbounded_ratio`/`unbounded_signed`). Used `unbounded_ratio`, matching the established convention for non-negative unbounded comparable scalars (`vol_ratio`, `garch_ratio`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migration file renumbered 243 → 255 (numbering collision)**
- **Found during:** Task 1, before applying the migration
- **Issue:** `production/migrations/243_vp_structural_primitives.sql` (the plan's literal filename) collides with an already-existing, already-merged migration (`243_frame_min_stop_price_fraction.sql`, todo 162's fix)
- **Fix:** Created the migration as `255_vp_structural_primitives.sql` instead (verified next-free number via `ls production/migrations/`)
- **Files modified:** `production/migrations/255_vp_structural_primitives.sql`
- **Verification:** Migration applies cleanly against the live DB (`psql -f`, `BEGIN`...`COMMIT` all succeed)
- **Committed in:** `4dc708f4` (Task 1 commit)

**2. [Rule 3 - Blocking] Column type and feature_registry schema corrected to match live DB**
- **Found during:** Task 1, before writing the migration
- **Issue:** The plan's action text specified `real` column type and an `is_bounded`/`is_directional` feature_registry format, both stale relative to the actual live schema (`information_schema.columns`, `\d feature_registry`)
- **Fix:** Used `double precision` (matches every other column) and the real feature_registry column set; `unbounded_ratio` normalization for the 5 S/R scalar/count fields (no precedent for `'none'`)
- **Files modified:** `production/migrations/255_vp_structural_primitives.sql`
- **Verification:** `\d feature_vectors`/`\d feature_registry` confirm the new columns/rows match the live table's existing conventions exactly
- **Committed in:** `4dc708f4` (Task 1 commit)

**3. [Rule 1 - Bug] Value-area tie-break bug in ported `_compute_session_value_area`**
- **Found during:** Task 2, synthetic verification of `update_session_vp()`
- **Issue:** The ported algorithm (verbatim from `ctx_VolumeProfile._compute_value_area`) selects the top-N-by-volume buckets via `np.argsort(vol_hist)[::-1]`, whose tie-breaking order is not guaranteed to match `np.argmax`'s "first occurrence" rule. Under exact volume ties (reproduced with a symmetric synthetic round-trip price path — real OHLCV data rarely ties exactly, but the invariant break is real), the POC's own bucket could be excluded from the 70%-cumulative-volume value-area selection entirely, silently violating `VAL <= POC <= VAH`
- **Fix:** Replaced the plain descending-volume sort with `np.lexsort` tie-broken by distance-from-POC-bucket, guaranteeing the POC bucket (distance 0, the unique minimum) is always selected first and is therefore always a member of the value-area bucket set
- **Files modified:** `src/intelligence/feature_cache.py`
- **Verification:** Synthetic 40-bar round-trip session test: `VAH >= POC >= VAL` holds after the fix (failed before it); full unit suite green
- **Committed in:** `0ff48698` (Task 2 commit)

**4. [Rule 3 - Blocking] FeatureVector construction blast radius from Task 1's new required fields**
- **Found during:** Task 2, running the full unit suite after Task 1's schema change
- **Issue:** Task 1 added 17 new required (no-default) fields to the `FeatureVector` dataclass. Every existing `FeatureVector(...)` construction site — `_build_feature_vector()`'s return statement, `_cold_start_vector()`'s direct construction, and 4 test files' hardcoded fixtures — broke with `TypeError: missing required argument`. 3 more test files had stale hardcoded field/column-count assertions (150/155/164) that failed once the counts became 172/181
- **Fix:** Added the 17 new params to `_build_feature_vector`'s keyword-only signature, defaulted to `None` (same avoid-blast-radius rationale already established for the canary fields); added the 17 fields as explicit `None` args to `_cold_start_vector`'s construction; updated the 4 test fixtures with real or `None` sentinel values; updated the 3 stale count assertions to 172/181
- **Files modified:** `src/intelligence/feature_factory.py`, `tests/unit/test_feature_factory.py`, `tests/unit/intelligence/test_feature_factory_p7.py`, `tests/unit/services/test_backfill_feature_factory.py`, `tests/unit/services/test_feature_vector_writer.py`, `tests/unit/services/test_feature_vector_writer_column_mapping.py`, `tests/unit/test_canary_predictors.py`
- **Verification:** Full unit suite green (`pytest tests/unit/ -q`, 0 failures); `services/feature_vector_pipeline.py` and `services/backfill_feature_factory.py` both import cleanly
- **Committed in:** `0ff48698` (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (2 Rule 3 blocking / schema-reality corrections in Task 1's migration, 1 Rule 1 bug fix, 1 Rule 3 blast-radius fix)
**Impact on plan:** All auto-fixes were necessary to keep the codebase in a correct, non-crashing state and to make the migration match the database it actually runs against. No scope creep — the mutator remains uninvoked (Plan 02's job) and no S/R computation was added (Plan 03's job).

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 can now wire `update_session_vp()` into both `compute()` (live) and `compute_batch()` (backfill) call sites, and derive the 12 ATR-normalized VP outputs from the mutator's raw `_sess_*` state plus the compute-path `atr_val`
- Plan 03 can now read `feature.sr.*` APR keys directly off `FeatureFactoryConfig` and write the 5 S/R fields (`resistance_strength`/`support_strength`/`resistance_age_bars`/`support_age_bars`/`sr_level_count`) alongside `sr_support_dist`/`sr_resist_dist`
- No blockers. `ic_engine`'s feature_registry alignment gate is satisfied (verified live) and will stay satisfied through Plans 02/03 since no further schema changes are needed — only computation wiring

---
*Phase: 163-vp-sr-structural-primitives*
*Completed: 2026-07-23*
