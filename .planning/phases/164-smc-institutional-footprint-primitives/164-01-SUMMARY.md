---
phase: 164-smc-institutional-footprint-primitives
plan: 01
subsystem: intelligence
tags: [feature-factory, smc, apr, timescaledb, feature-cache, config-service]

# Dependency graph
requires:
  - phase: 163-vp-sr-structural-primitives
    provides: "_STRUCTURAL_VP_SR_FIELD_NAMES append-only persistence slice pattern, update_session_vp() FeatureCache mutator template"
provides:
  - "36 new feature_vectors columns (ATR-distance/bounded/count/ordinal only, zero raw price levels) + matching feature_registry rows"
  - "FeatureVector dataclass with all 36 SMC fields threaded through _build_feature_vector as None placeholders (172 -> 208 total fields)"
  - "_SMC_FIELD_NAMES persistence slice, fully wired through INSERT column list, placeholder generator, _TOTAL_COLUMNS, params tuple"
  - "39 feature.smc.* APR keys (config_schema/config_state/config_history) covering every hardcoded numeric constant in the 8 archived smc_context plugins"
  - "FeatureFactoryConfig with 39 smc_* fields, wired from APR in both feature_vector_pipeline.py (live) and backfill_feature_factory.py (batch)"
  - "FeatureCache.update_overnight_range() mutator + 4 exposed AMD state fields + 3 internal overnight-range accumulators (not yet invoked)"
affects: ["164-02-order-blocks-breaker-mitigation", "164-03-fvg-sweeps-pools", "164-04-zones-bos-choch-amd"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "APR namespace feature.smc.<concept>.* (per-plugin-concept nesting, not flat feature.smc.*)"
    - "Session-boundary-reset FeatureCache mutator keyed on UTC-hour cycle-day derivation (accumulation-phase hour >= threshold belongs to today's cycle, else prior calendar day) -- generalizes update_wk_vwap()'s ISO-week-key pattern to a non-calendar-week boundary"

key-files:
  created: []
  modified:
    - production/migrations/266_smc_institutional_footprint.sql
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - src/intelligence/feature_cache.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/test_canary_predictors.py
    - tests/unit/test_feature_factory.py

key-decisions:
  - "Migration renumbered 259 -> 266 at execution time (259 claimed by a concurrent todo-183 fix mid-session, anticipated and documented in 164-RESEARCH.md Open Question 3)"
  - "feature_registry.group_name = 'structure' not 'smart_money' (live CHECK constraint enum doesn't include 'smart_money'; FEATURE_VECTOR_DOMAIN's Python-side tag still uses 'smart_money' per A5, a separate unconstrained vocabulary)"
  - "ATR-recompute constants (14-bar window, 20-bar std fallback) in liquidity_pools.py/supply_demand_zones.py deliberately NOT ported to APR -- Plans 02-04 reuse the already-computed atr_val per 164-RESEARCH.md's Don't-Hand-Roll guidance, so those constants never enter the codebase"
  - "AMD manipulation-detection adapted to an intrabar high/low proxy (no close parameter in the mutator's fixed signature) instead of the archived plugin's close-based reversal test -- documented explicitly in the method docstring as an adaptation, not a silent behavior change"

patterns-established:
  - "39-key APR block for a single contract-only plan (Task 2), all [conventional] provenance, defaulted FeatureFactoryConfig fields appended at dataclass end to avoid touching ~6 pre-existing direct construction sites"

requirements-completed: ["REQ-164-09"]

# Metrics
duration: 35min
completed: 2026-07-27
---

# Phase 164 Plan 01: SMC Institutional Footprint Data Contract Summary

**Migration 266 + FeatureVector/domain/persistence contract for 36 SMC fields, 39 feature.smc.* APR keys wired into both live and batch FeatureFactoryConfig sites, and a new FeatureCache.update_overnight_range() AMD mutator -- contract-only, zero compute logic, ready for Plans 02-04.**

## Performance

- **Duration:** ~35 min (this session; Task 1 was completed and verified in a prior session but left uncommitted)
- **Started:** 2026-07-27T21:15:00-04:00 (approx, session resume)
- **Completed:** 2026-07-27T21:41:31-04:00
- **Tasks:** 3 (Task 1 verified-complete from prior session, committed this session; Task 2 and Task 3 executed this session) + 1 test-fix commit
- **Files modified:** 13 (7 source/migration, 6 test)

## Accomplishments
- Committed Task 1's already-verified work (uncommitted in the working tree at session start): migration 266 Sections 1+2 (36 columns + 36 registry rows), FeatureVector's 36 new fields, FEATURE_VECTOR_DOMAIN entries, `_build_feature_vector` threading, `_SMC_FIELD_NAMES` persistence slice
- Enumerated every hardcoded numeric constant across the 8 archived `smc_context` plugin files and seeded 39 `feature.smc.*` APR keys (migration 266 Section 3), each with `[conventional]` provenance and "Not an ML learning target"
- Added 39 `smc_*` fields to `FeatureFactoryConfig`, wired from APR in both `feature_vector_pipeline.py` (`_THRESHOLD_KEYS` + `_prewarm_threshold_config()`) and `backfill_feature_factory.py` (`_build_feature_factory_config()`)
- Built `FeatureCache.update_overnight_range()` -- a session-boundary-reset mutator tracking AMD accumulation-phase overnight high/low with UTC-hour cycle-key derivation, plus a manipulation-detection check adapted to the mutator's high/low-only signature; verified with a synthetic multi-day sweep (accumulation extends range, manipulation/distribution hold it fixed, a new accumulation cycle resets it, manipulation fires exactly once per cycle)
- Fixed 9 hardcoded field-count assertions across 6 test files that broke when Task 1 landed 36 new columns (172->208 fields, 181->217 persisted params) -- same recurring pattern every phase before this one hit; full `tests/unit/` suite is green (0 failures)

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 266 columns+registry + FeatureVector/domain/persistence contract** - `3cd96631` (feat) -- committed this session after re-verifying against the plan's own automated gates (was complete but uncommitted from a prior session)
2. **Task 2: Migration 266 Section 3 APR seeds + FeatureFactoryConfig SMC fields + wire both config sites** - `e423b45e` (feat)
3. **Task 3: FeatureCache.update_overnight_range() mutator + AMD state fields** - `c1ef3991` (feat)
4. **Test fixes: stale field-count assertions** - `1d1d326a` (test) -- small early commit per the status note, unblocks a clean `pytest tests/unit/ -q` run

_No TDD tasks in this plan; all three are `type="auto"`._

## Files Created/Modified
- `production/migrations/266_smc_institutional_footprint.sql` - 36 columns + 36 registry rows + 39 APR keys (3-section migration, mirrors migration 255's template)
- `src/intelligence/schemas.py` - 36 new `FeatureVector` fields (`float | None`, one contiguous smart-money block), docstring group table + Total 172->208
- `src/intelligence/feature_factory.py` - 36 `FEATURE_VECTOR_DOMAIN` entries, `_build_feature_vector` threading at both call sites, 39 `smc_*` `FeatureFactoryConfig` fields + docstring APR mapping
- `src/intelligence/features/feature_vector_persistence.py` - `_SMC_FIELD_NAMES` slice threaded through INSERT SQL, placeholder generator, `_TOTAL_COLUMNS`, params tuple
- `src/intelligence/feature_cache.py` - `update_overnight_range()` mutator, 4 exposed AMD fields, 3 internal overnight-range accumulators
- `services/feature_vector_pipeline.py` - 39 `feature.smc.*` keys in `_THRESHOLD_KEYS` + `_prewarm_threshold_config()` wiring
- `services/backfill_feature_factory.py` - matching 39-key `cfg.get_sync()` wiring in `_build_feature_factory_config()`
- 6 test files - stale field-count assertions updated (172->208, 181->217, plus one new test replacing a now-false "last element" claim)

## Decisions Made
- Migration renumbered 259 -> 266 at execution time; 259 was claimed by a concurrent session's unrelated todo-183 fix mid-plan-authoring, an anticipated collision per 164-RESEARCH.md Open Question 3 (documented in the migration's own header, not a surprise)
- `feature_registry.group_name` set to `'structure'` rather than the plan's proposed `'smart_money'` -- live schema has a CHECK constraint enumerating valid group_name values that doesn't include `'smart_money'`; discovered and fixed during Task 1 (documented in the migration header). `FEATURE_VECTOR_DOMAIN`'s Python-side tag is unconstrained and still uses `'smart_money'` per the research doc's A5 recommendation -- these are two independent vocabularies, not a contradiction
- ATR-recompute constants found in `liquidity_pools.py`/`supply_demand_zones.py` (a redundant 14-bar/20-bar ATR window, separate from the already-computed `atr_val` threaded into `compute()`) were deliberately excluded from the 39 APR keys -- 164-RESEARCH.md's "Don't Hand-Roll" table flags recomputing ATR inline as an anti-pattern; Plans 02-04 will reuse `atr_val`, so these constants should never enter the codebase at all, APR-backed or not
- AMD manipulation-detection logic was adapted (not ported verbatim) to the mutator's fixed 4-argument signature (`bar_ts, high, low, config` -- no `close`): the archived plugin's "breach then close back inside range" test becomes "breach then wick back inside range within the same bar" using high/low only. Documented explicitly in the method docstring as an intentional adaptation

## Deviations from Plan

None - plan executed as written, including its own explicit renumbering/renaming corrections (259->266, migration-1-vs-2 sequencing) that were already anticipated in the plan text and research doc.

### Auto-fixed Issues (Rule 2 - captured to unblock a clean test run, not scope creep)

**1. [Rule 2 - missing critical functionality] Stale field-count assertions across 6 test files**
- **Found during:** Post-Task-3 full suite verification (`pytest tests/unit/ -q`)
- **Issue:** 9 tests across `test_feature_factory_p7.py`, `test_backfill_feature_factory.py`, `test_feature_vector_writer.py` (x3), `test_feature_vector_writer_column_mapping.py` (x2), `test_canary_predictors.py` (x2), `test_feature_factory.py` hardcoded the pre-Phase-164 field/param counts (172/181/159/180) and the assumption that `sr_level_count` was the persisted tuple's last element -- both broken by Task 1's 36 new columns
- **Fix:** Updated all count assertions to the new correct totals (208 fields, 217 params) and docstrings; added `test_manip_strength_at_index_216_is_last_element` to replace the now-false `sr_level_count`-is-last claim with the correct new tail position
- **Files modified:** the 6 test files listed above
- **Verification:** `pytest tests/unit/ -q` — 0 failures, full suite green
- **Committed in:** `1d1d326a`

---

**Total deviations:** 1 auto-fixed test-maintenance pass (Rule 2), explicitly called out and pre-authorized in this plan's own execution status note
**Impact on plan:** No scope creep -- this is required test maintenance to keep the suite usable, matching the exact pattern every prior phase (163, 143.1, migration 206/211/223) hit when adding `FeatureVector` columns.

## Issues Encountered
None beyond the anticipated migration-renumbering collision (already resolved by the prior session's Task 1 work and documented in the migration header) and the working-tree state where Task 1 was complete but uncommitted at this session's start (resolved by re-verifying Task 1's own automated gates before committing it as its own atomic commit).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plans 02 (order blocks/breaker/mitigation), 03 (FVG/sweeps/pools), 04 (zones/BOS-CHoCH/AMD) can now replace `None` placeholders with real computed values against a fixed, drift-free contract (registry==dataclass, persistence slice complete, all 39 APR knobs already seeded and wired)
- `FeatureCache.update_overnight_range()` is delivered and unit-verified but genuinely not invoked anywhere yet -- Plan 04 must add the compute_batch loop, live per-bar handler, and warm-up replay call sites alongside AMD's `compute()` derivation (which also owns the `amd_phase` ordinal encoding and `manip_strength` `[0,1]` clamp, neither implemented in this plan by design)
- No blockers. Full `tests/unit/` suite green (0 failures), ruff/black clean on every touched file.

## Known Stubs
All 36 SMC `FeatureVector` fields persist as `NULL` until Plans 02-04 land (intentional, contract-only plan per its own objective) -- not a stub in the "unfinished feature" sense; documented in the plan's own truths/artifacts and re-stated here per the executor's stub-tracking requirement so the verifier doesn't flag it as an unexpected gap:
- `src/intelligence/feature_factory.py` -- all 36 SMC kwargs passed as `None` at both `_build_feature_vector` call sites (`compute()`, `compute_batch()`)
- `src/intelligence/feature_cache.py` -- `update_overnight_range()` exists but has zero call sites in this plan (by design, per its own `<done>` criteria: "Not yet called anywhere")

---
*Phase: 164-smc-institutional-footprint-primitives*
*Completed: 2026-07-27*

## Self-Check: PASSED

All 8 key files verified present; all 4 commit hashes (3cd96631, e423b45e, c1ef3991, 1d1d326a) verified present in git log.
