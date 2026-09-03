---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 01
subsystem: database
tags: [postgresql, timescaledb, concept_registry, feature_registry, migration, plpgsql, asyncpg]

requires: []
provides:
  - concept_parent multi-parent lineage join table with FK-enforced referential integrity on both edges
  - fn_concept_parent_cycle_guard() trigger rejecting cycles on both INSERT and UPDATE
  - fn_cascade_concept_parent_deprecation() cross-domain cascade trigger (BUG-1/BUG-2 fixed vs feature_registry original)
  - concept_registry.is_control/control_expectation/group_name identity columns
  - concept_gate.consecutive_shadow_passes/observations_since_demotion recovery counters
affects: [170-03, 170-06, 170-07, 170-08]

tech-stack:
  added: []
  patterns:
    - "Recursive CTE cycle guard (BEFORE INSERT OR UPDATE) protecting a self-recursive AFTER UPDATE cascade trigger"
    - "Log-before-update ordering in cascade triggers so the audit INSERT sees pre-cascade status, not post-cascade"

key-files:
  created:
    - production/migrations/283_concept_registry_feature_domain_schema.sql
    - tests/integration/test_concept_parent_lineage.py
  modified: []

key-decisions:
  - "concept_registry.parent_concept_id (single-parent FK) is NOT dropped -- domain='ensemble_strategy' may still reference it; concept_parent is additive, feature domain uses it exclusively"
  - "group_name given a dedicated indexable column on concept_registry (not folded into metadata JSONB) because ops_ic_shrinkage.py/ops_ensemble_ablation.py/ops_broadcast_feature_audit.py do real SQL-level WHERE/DISTINCT filtering on it today"
  - "No new APR keys minted for L-5 recovery counters -- feature domain reuses the existing alpha.decay.recovery_min_observations/recovery_min_passes keys ic_engine already reads"
  - "Fixed BUG-1 (audit-before-update ordering) and BUG-2 (fabricated 'active' from_status) from feature_registry's original cascade trigger rather than carrying them into the replacement, per todo 118's literal SQL"
  - "First DB-touching test in the concept-registry test family placed under tests/integration/ with the existing migrated_test_database fixture, not a new fixture mechanism"

requirements-completed: [L-5, L-8, L-9, L-10]

duration: 11min
completed: 2026-08-04
---

# Phase 170 Plan 01: Concept Registry Feature-Domain Schema Gaps Summary

**Migration 283 adds concept_parent (multi-parent lineage with a recursive cycle guard), a cross-domain cascade-deprecation trigger fixing two real audit bugs in the feature_registry original, and the identity/recovery columns feature_registry has that concept_registry didn't -- proven against a live database by 5 new integration tests, zero feature rows seeded.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-08-04T10:29:41-04:00
- **Completed:** 2026-08-04T10:39:20-04:00
- **Tasks:** 2
- **Files modified:** 2 (both new)

## Accomplishments
- Closed all four one-way-door schema gaps (todo 118 L-5/L-8/L-9/L-10) between `feature_registry` and `concept_registry`/`concept_gate` before `feature_registry` is DROPped later in this phase
- Generalized `feature_registry`'s cascade-deprecation trigger to work across every `concept_registry` domain via the new `concept_parent` join table, fixing BUG-1 (audit INSERT ran after the UPDATE, silently logging zero rows) and BUG-2 (hard-coded `'active'` `from_status`, corrupting the audit trail for `shadow_only`/`candidate` children)
- Proved the cycle guard rejects cycles on both its declared `BEFORE INSERT OR UPDATE` paths, and proved multi-level cascade recursion (grandparent -> parent -> child) actually fires, with executed tests against a real database rather than declared-but-unfired triggers

## Task Commits

Each task was committed atomically:

1. **Task 1: Write and apply migration 283** - `b0f9f371` (feat)
2. **Task 2: Prove the cycle guard and cascade trigger against a real database** - `8cce6139` (test)

## Files Created/Modified
- `production/migrations/283_concept_registry_feature_domain_schema.sql` - `concept_parent` table + `fn_concept_parent_cycle_guard()` + `fn_cascade_concept_parent_deprecation()` + `concept_registry.is_control/control_expectation/group_name` + `concept_gate.consecutive_shadow_passes/observations_since_demotion`; applied to live `indicagent`
- `tests/integration/test_concept_parent_lineage.py` - 5 tests against `indicagent_test`: multi-parent lineage, cycle rejection (INSERT + UPDATE paths + self-edge), single-level cascade with true-from_status audit fidelity, multi-level cascade recursion

## Decisions Made
- `concept_registry.parent_concept_id` stays; `concept_parent` is additive and feature-domain-exclusive (see key-decisions above)
- `group_name` gets a real column, not JSONB, matching the same rule already applied to `is_control` (live SQL-level filtering by three ops scripts)
- No new APR keys for L-5; reuse `alpha.decay.recovery_min_observations`/`alpha.decay.recovery_min_passes`
- Both BUG-1 and BUG-2 in the feature_registry original (and in todo 118's literal proposed SQL) are fixed in the replacement, not carried forward
- The new lineage test is DB-backed and lives under `tests/integration/`, the first DB-touching test in the concept-registry family (existing tests in `tests/unit/test_concept_registry_service.py` are pure-helper, no DB)

## Deviations from Plan

None - plan executed exactly as written. One implementation-detail addition not explicitly specified by the plan: `asyncpg.Connection` uses `__slots__` and cannot carry ad-hoc test-bookkeeping attributes, so the test file wraps the connection in a small `_TrackedConnection` helper to track per-test created `concept_id`s for teardown. This is test-infrastructure plumbing, not a behavior or schema deviation, and required no plan change.

## Issues Encountered
- The worktree has no `.venv` (gitignored, not copied into worktrees) -- ran `pytest`/`ruff`/`black` via the main checkout's `.venv/bin/` and via `PATH` prepend for the pre-commit hook's tool lookup. No code impact; noted for awareness on future worktree-executed DB/test plans.

## User Setup Required

None - no external service configuration required. Migration was applied directly to the live `indicagent` database as part of Task 1 (per plan: migrations are applied by hand, no `schema_migrations` tracking table in this project).

## Next Phase Readiness
- `concept_parent`, the cycle guard, and the cascade trigger are live and proven; Plan 03 (the `domain='feature'` fold-in / row migration) can now land without a schema gap
- Plan 07 (lineage-reader trace + ordinality invariance test) and Plan 06/08 (repointing consumers) are unblocked at the schema level
- `production/migrations/284_...` (the feature-domain row seed, referenced throughout migration 283's header) is the next migration number to use

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*

## Self-Check: PASSED

- FOUND: production/migrations/283_concept_registry_feature_domain_schema.sql
- FOUND: tests/integration/test_concept_parent_lineage.py
- FOUND: .planning/milestones/v3.1-phases/170-concept-registry-feature-domain-migration-feature-registry-r/170-01-SUMMARY.md
- FOUND: b0f9f371 (Task 1 commit)
- FOUND: 8cce6139 (Task 2 commit)
- FOUND: f959efc8 (docs: SUMMARY commit)
