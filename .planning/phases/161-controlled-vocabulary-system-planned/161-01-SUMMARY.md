---
phase: 161-controlled-vocabulary-system
plan: 01
subsystem: database
tags: [postgresql, migrations, controlled-vocabulary, regime, taxonomy]

# Dependency graph
requires: []
provides:
  - "controlled_vocabulary table: flat (namespace, code) -> label/description/sort_order registry"
  - "vocabulary_group table: named overlapping groupings within a namespace"
  - "vocabulary_group_member table: composite-FK join table for group membership"
  - "6 live namespaces seeded: regime_hmm (5), regime_cross_sectional_equity (9), regime_cross_sectional_rates (6), timeframe (5), asset_class (3), tier (3)"
  - "vocabulary_group seeds for regime_hmm (trending/transition/bullish_bias/bearish_bias) and the crossed-facet groups for both regime_cross_sectional_* namespaces"
affects: [161-02, 161-03, VocabularyService, vocabulary_drift, /api/vocabulary]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Registry-family migration shape: CREATE TABLE IF NOT EXISTS + composite PK/FK + COMMENT ON TABLE (mirrors migration 233)"
    - "ON CONFLICT DO NOTHING seed idempotency keyed on the natural composite PK, no WHERE NOT EXISTS fallback needed"
    - "Crossed-facet vocabulary_group seeding: two independent group families per namespace so a code belongs to exactly one member of each family"

key-files:
  created:
    - production/migrations/239_controlled_vocabulary_schema.sql
    - production/migrations/240_controlled_vocabulary_seed_namespaces.sql
  modified: []

key-decisions:
  - "Renumbered from planned 237/238 to 239/240 - both target numbers were already taken by Phase 146 (237_tag_vocabulary_taxonomy_cleanup.sql, 238_tag_calibrator_measurement_contract.sql), shipped the same day this plan executed. Applied the plan's own documented fallback."
  - "Live-reverified all 6 namespace code counts and group counts against the current DB (market_regimes, feature_registry, market_data_ohlcv, instruments) before seeding rather than trusting the plan's cited counts blindly - all matched exactly."
  - "Reworded migration 239's D-02 explanatory comments to avoid the literal strings 'tag_vocabulary'/'instrument_tags' after the first application tripped the plan's own grep-based acceptance check (grep -c 'tag_vocabulary\\|instrument_tags\\|CREATE TYPE' must return 0) - the check is a blunt literal-string grep, so descriptive prose naming those tables (even non-destructively, to explain the D-02 boundary) fails it. Preserved the epistemic-distinction content using paraphrase instead."

requirements-completed: []

# Metrics
duration: ~25min
completed: 2026-07-18
---

# Phase 161 Plan 01: Controlled Vocabulary Schema + Seed Summary

**Three-table Controlled Vocabulary registry (migrations 239/240, renumbered from planned 237/238) live in the database, seeded with all 6 locked namespaces and their overlapping/crossed-facet vocabulary groups, verified idempotent on re-run.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-18T00:00:00Z (approx)
- **Completed:** 2026-07-18T00:16:07Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (both new)

## Accomplishments
- `controlled_vocabulary` / `vocabulary_group` / `vocabulary_group_member` tables created with the design-doc composite-key shape and full FK integrity, verified via `\d` against the live schema.
- All 6 live namespaces seeded with exactly the code counts specified in the plan (5/9/6/5/3/3 = 31 total codes), each live-reverified against the current DB state (`market_regimes`, `feature_registry`, `market_data_ohlcv`, `instruments`) rather than trusted from the plan text alone.
- `regime_hmm`'s overlapping trending/transition/bullish_bias/bearish_bias groups and both `regime_cross_sectional_*` namespaces' crossed vol-tier/direction and curve-shape/width facet groups all seeded per D-03/D-04/D-04b.
- Both migrations verified idempotent: re-running each a second time exits 0 with zero new rows inserted / `NOTICE: relation already exists, skipping` for the schema.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create migration 239 (renamed from 237) - three-table Controlled Vocabulary schema** - `942ef3fa` (feat)
2. **Task 2: Create migration 240 (renamed from 238) - seed 6 namespaces + vocabulary groups** - `75e4326d` (feat)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified
- `production/migrations/239_controlled_vocabulary_schema.sql` - 3-table registry DDL (controlled_vocabulary, vocabulary_group, vocabulary_group_member), composite PKs, composite FKs, epistemic-kind COMMENT ON TABLE per table
- `production/migrations/240_controlled_vocabulary_seed_namespaces.sql` - seed rows for all 6 namespaces + vocabulary_group/vocabulary_group_member rows for regime_hmm and both regime_cross_sectional_* namespaces

## Decisions Made
- **Migration renumbering (237/238 -> 239/240):** the plan's Task 1 explicitly instructed checking `ls production/migrations/ | grep '^237'` first and falling back to the next free integer if taken, noting it in the SUMMARY. Both 237 and 238 were taken by Phase 146 (shipped the same day: `237_tag_vocabulary_taxonomy_cleanup.sql`, `238_tag_calibrator_measurement_contract.sql`). Used 239/240, the next free consecutive pair, preserving the schema-then-seed migration ordering the plan specifies.
- **Live re-verification over trusting cited counts:** queried `market_regimes`, `feature_registry`, `market_data_ohlcv`, and `instruments` directly before writing the seed migration, confirming all 6 namespace code counts and both `regime_cross_sectional_*` group counts (4/6/5) matched the plan's acceptance criteria exactly - no drift found since the pattern-mapping pass.
- **Comment wording adjusted for the D-02 grep gate:** the schema migration's acceptance criteria include a literal grep for `tag_vocabulary|instrument_tags|CREATE TYPE` that must return 0, meant to confirm no shared table/FK/ENUM bridges this registry to the existing tag-assignment system. The first draft's `COMMENT ON TABLE` prose named those tables directly to explain the D-02 epistemic distinction (authoritative/flat vs. weighted/falsifiable-hypothesis rows) and tripped the check even though it introduced no actual coupling. Reworded to describe the distinction without using the literal table-name strings; re-verified `grep -c` returns 0 and the migration still applies/idempotency-checks cleanly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migration numbers 237/238 already taken, renumbered to 239/240**
- **Found during:** Task 1, pre-write check (`ls production/migrations/ | grep '^237'`)
- **Issue:** Plan's target migration numbers 237 and 238 were already occupied by Phase 146's migrations (shipped 2026-07-17, the day before this plan executed).
- **Fix:** Used the plan's own documented fallback - next free consecutive integers, 239 and 240. File names, content, and all acceptance criteria otherwise unchanged (criteria text in this SUMMARY references the renumbered files).
- **Files modified:** `production/migrations/239_controlled_vocabulary_schema.sql`, `production/migrations/240_controlled_vocabulary_seed_namespaces.sql`
- **Verification:** Both migrations apply cleanly against the live DB and pass every acceptance criterion specified in the plan.
- **Committed in:** `942ef3fa`, `75e4326d`

**2. [Rule 1 - Bug] Migration 239's D-02 comment text tripped its own acceptance-criteria grep gate**
- **Found during:** Task 1, acceptance-criteria verification pass
- **Issue:** The migration's `grep -c 'tag_vocabulary\|instrument_tags\|CREATE TYPE'` acceptance check requires 0 matches, but the initial `COMMENT ON TABLE` and header prose explaining D-02's distinction from the existing tag-assignment system used those literal table names, returning 6 matches.
- **Fix:** Reworded all comment prose to describe the epistemic distinction (authoritative/flat vocabulary rows vs. confidence-weighted/falsifiable-hypothesis assignment rows) without using the literal `tag_vocabulary`/`instrument_tags` strings. Re-applied the migration to the live DB after the edit.
- **Files modified:** `production/migrations/239_controlled_vocabulary_schema.sql`
- **Verification:** `grep -c 'tag_vocabulary\|instrument_tags\|CREATE TYPE' production/migrations/239_controlled_vocabulary_schema.sql` now returns 0; migration still applies and idempotency-checks cleanly.
- **Committed in:** `942ef3fa`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes are mechanical (numbering fallback the plan itself specified; wording fix to satisfy the plan's own literal acceptance check). No scope creep, no schema/seed content changes beyond what the plan specified.

## Issues Encountered
None beyond the two auto-fixed deviations above.

## User Setup Required
None - no external service configuration required. Both migrations applied directly against the live `indicagent` database as part of task execution.

## Next Phase Readiness
- The storage foundation (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`) is live and seeded, ready for `VocabularyService` (161-02 or later plan) to build its cached-read layer on top.
- All 6 namespaces + groups verified against live DB state as of 2026-07-18 - no drift since the 161-PATTERNS.md pattern-mapping pass.
- No blockers. The corpus re-run (143.1-07) referenced in STATE.md continues unaffected - this plan touched only the three new tables, never `feature_ic_scores`, `market_data_ohlcv`, or `alpha_frames`.

---
*Phase: 161-controlled-vocabulary-system*
*Completed: 2026-07-18*
