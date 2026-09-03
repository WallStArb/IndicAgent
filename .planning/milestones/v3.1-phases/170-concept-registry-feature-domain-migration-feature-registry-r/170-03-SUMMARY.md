---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 03
subsystem: database
tags: [postgresql, timescaledb, concept_registry, feature_registry, migration, asyncpg, data-integrity]

requires:
  - phase: 170-01
    provides: concept_parent lineage table, cascade-deprecation trigger, is_control/control_expectation/group_name columns on concept_registry, consecutive_shadow_passes/observations_since_demotion on concept_gate
provides:
  - domain='feature' fully materialized in concept_registry/concept_gate/concept_parent (249 rows each / 16 edges), replayed transition history in concept_transition_log (249 genesis rows + 2 replayed rows), and 2 tombstone concept_registry rows for orphaned feature_transition_log entries
  - re-runnable parity verifier (ops_concept_feature_migration_verify.py), 11 checks, --json mode, SKIPPED-on-drop behavior for Plan 08
affects: [170-04, 170-06, 170-07, 170-08]

tech-stack:
  added: []
  patterns:
    - "Tombstone concept_registry rows (metadata->>'migrated_from'='feature_transition_log') for audit-trail identities whose source row no longer exists, so an immutable append-only log never dangles a foreign key to a table about to be dropped"
    - "Commit-flip-verify-revert-commit negative-control test for a DB-state verifier, in place of a same-process rollback trick that cannot work across a shelled-out subprocess under MVCC"

key-files:
  created:
    - production/migrations/284_concept_registry_feature_domain_seed.sql
    - scripts/ops/alpha/ops_concept_feature_migration_verify.py
  modified: []

key-decisions:
  - "2 feature_transition_log rows (new_high_flag, new_low_flag) reference feature_names fully removed from feature_registry, not the interfaces block's assumed always-resolvable case -- fixed with 2 tombstone concept_registry rows carrying no concept_gate row and no genesis_seed row, distinguished from the 249 real rows via metadata->>'migrated_from'='feature_transition_log'"
  - "Row-count parity check scoped to metadata->>'migrated_from'='feature_registry' (249=249) rather than unscoped domain='feature' (251) -- every other must-have (gate parity, lineage-edge count, genesis-row count) is naturally unaffected since none of those queries touch tombstone rows"
  - "Plan's suggested rollback-based negative-control test (shell out to psql mid-transaction, run verifier, ROLLBACK) does not work: a separate subprocess is a separate connection and cannot see an uncommitted UPDATE under default READ COMMITTED isolation -- confirmed empirically before relying on it. Used a real commit-flip-verify-revert-commit cycle on a zero-lineage leaf feature (momentum_z_fast) instead, so no cascade trigger side effects needed reverting"
  - "Genesis rows (step 4) source strictly from feature_registry, matching the plan's literal design -- tombstones never received a fabricated genesis_seed row since they were never a live incumbent"

requirements-completed: [S-1, L-7]

duration: 18min
completed: 2026-08-04
---

# Phase 170 Plan 03: Concept Registry Feature-Domain Migration + Seed Summary

**Migration 284 folds all 249 `feature_registry` rows into `concept_registry`/`concept_gate`/`concept_parent` and replays the full `feature_transition_log` audit trail (including 2 orphaned rows for features already removed from `feature_registry`) into `concept_transition_log`, proven idempotent by an actual second apply and validated by an 11-check re-runnable parity verifier that was proven to fail via a real injected mismatch.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-08-04T12:48:00-04:00
- **Completed:** 2026-08-04T13:06:20-04:00
- **Tasks:** 2
- **Files modified:** 2 (both new)

## Accomplishments
- Closed the one-way-door data migration for todo 118 scope item 1: 249 `concept_registry` rows, 249 `concept_gate` rows, 16 `concept_parent` lineage edges, 249 genesis transitions, and a full `feature_transition_log` replay -- all inside a single transaction with two hard `RAISE EXCEPTION` assertions (lineage-edge-count, replay-count) that would have aborted the whole migration on any silent data loss
- Discovered and fixed a real live-data gap the plan's `<interfaces>` snapshot didn't anticipate: 2 `feature_transition_log` rows point at feature names that no longer exist anywhere in `feature_registry` (fully removed, not merely `status='deprecated'`) -- fixed with 2 tombstone `concept_registry` rows so the replay's `concept_id` foreign key has something valid to attach the preserved history to, consistent with the migration's own "nothing is left pointing back at a table that is about to be dropped" mandate
- Proved idempotency for real: applied migration 284 to the live `indicagent` database twice, confirmed every count (row parity, gate parity, lineage-edge parity, genesis-row parity, replay-row parity, `ensemble_strategy` row/transition counts) identical before and after the second apply
- Built and proved `ops_concept_feature_migration_verify.py`: 11 independently-reported PASS/FAIL checks, `--json` machine-readable output, graceful `SKIPPED`/exit-0 behavior once `feature_registry` is eventually dropped (Plan 08) -- and actually demonstrated the verifier can fail (not just claimed it), via a real commit-flip-verify-revert-commit cycle rather than the plan's suggested rollback trick, which was confirmed empirically not to work across a separate subprocess connection

## Task Commits

Each task was committed atomically:

1. **Task 1: Write and apply migration 284 (seed domain='feature' + replay the transition log)** - `c195f16d` (feat)
2. **Task 2: Write the re-runnable feature_registry <-> concept_registry parity verifier** - `fd7228fd` (test)

## Files Created/Modified
- `production/migrations/284_concept_registry_feature_domain_seed.sql` - DATA-only migration: seeds 249 `concept_registry` rows (domain='feature'), 249 `concept_gate` rows, 16 `concept_parent` edges (with a hard integrity assertion), 249 genesis `concept_transition_log` rows, a full `feature_transition_log` replay (with a hard completeness assertion), and 2 tombstone `concept_registry` rows for orphaned transition-log entries. Applied to live `indicagent` twice; both applies leave identical counts.
- `scripts/ops/alpha/ops_concept_feature_migration_verify.py` - 11-check re-runnable parity verifier (`--json` mode), consumed as a gate by Plan 06 and Plan 08. Ruff/black clean.

## Decisions Made
- See `key-decisions` in frontmatter. Summary: tombstone rows solve the orphaned-transition-log-entry gap without any schema change (staying inside this plan's DATA-only scope guard); the row-count parity check and its verifier counterpart are scoped to exclude tombstones so the 249=249 invariant the plan states stays literally true; the negative-control test methodology was corrected from a non-functional rollback trick to a real commit/revert cycle chosen specifically to avoid the cascade-deprecation trigger's side effects.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Orphaned feature_transition_log rows would abort every migration apply**
- **Found during:** Task 1, first apply attempt
- **Issue:** The plan's `<interfaces>` snapshot measured `feature_transition_log` count=2 but didn't check whether those rows' `feature_name`s still resolve in `feature_registry`. They don't: `new_high_flag` and `new_low_flag` were fully removed from `feature_registry` at some point in project history (not merely deprecated). The replay step's `JOIN concept_registry cr ON cr.name = ftl.feature_name` therefore matched zero rows, the replay-count hard assertion (`2 source rows vs 0 replayed`) fired exactly as designed, and the whole transaction rolled back.
- **Fix:** Added a new migration step seeding 2 tombstone `concept_registry` rows (`metadata->>'migrated_from'='feature_transition_log'`, distinct from the 249 real rows sourced from `feature_registry`) for any `feature_transition_log` feature_name absent from `feature_registry`, giving the replay a valid `concept_id`. These rows carry no `concept_gate` row and receive no `genesis_seed` row (genesis seeding still sources strictly from `feature_registry`, per the plan's literal design -- a tombstone was never a live incumbent).
- **Files modified:** `production/migrations/284_concept_registry_feature_domain_seed.sql`
- **Verification:** Migration applied cleanly (all inserts succeeded, both hard assertions passed); re-applied a second time with all counts unchanged; parity verifier's `replay_completeness` check confirms 2==2 with all rows matched.
- **Committed in:** `c195f16d` (Task 1 commit)

**2. [Rule 1 - Bug] Row-count parity check needed scoping to exclude tombstones**
- **Found during:** Task 1, after fixing deviation 1
- **Issue:** With 2 tombstone rows added, `count(concept_registry WHERE domain='feature')` = 251, not 249 -- breaking the plan's literal `SELECT count(*) ... = SELECT count(*) FROM feature_registry` acceptance check if left unscoped.
- **Fix:** Scoped the row-count parity check (both my own manual verification pass and the Task 2 verifier's `row_count_parity` check) to `metadata->>'migrated_from'='feature_registry'`. Confirmed every other acceptance criterion (gate parity, lineage-edge count, genesis-row count, control-name match, enabled invariant, status parity) is naturally unaffected -- none of those queries touch tombstone rows, since they all derive from real `feature_registry` joins.
- **Files modified:** `production/migrations/284_concept_registry_feature_domain_seed.sql` (header comment documenting the scoping), `scripts/ops/alpha/ops_concept_feature_migration_verify.py` (`_REAL_ROW_SCOPE` constant)
- **Verification:** All 11 verifier checks PASS against live data; manual scoped-count query confirms 249=249.
- **Committed in:** `c195f16d`, `fd7228fd`

**3. [Rule 1 - Bug] Plan's suggested negative-control test methodology doesn't work**
- **Found during:** Task 2, negative-control proof
- **Issue:** The plan suggests proving the verifier can fail via `psql -c "BEGIN; UPDATE ...; ! verify.py; ROLLBACK;"`. Tested this literally (via a `-f` script file, since `-c` doesn't parse backslash meta-commands at all): the shelled-out verifier process is a separate database connection, and under PostgreSQL's default READ COMMITTED isolation a separate connection cannot see another transaction's uncommitted UPDATE. Empirically confirmed: a parallel `SELECT status` from a second connection returned the pre-UPDATE value while the first transaction was still open.
- **Fix:** Used a real commit-flip-verify-revert-commit cycle instead: (1) confirmed `momentum_z_fast` has zero parent/child `concept_parent` edges, so flipping its status cannot fire the cascade-deprecation trigger; (2) `UPDATE ... SET status='deprecated'` and committed; (3) ran the verifier -- `status_parity` and `enabled_invariant` both correctly FAILed, exit code 1; (4) reverted the status to `'active'` and committed; (5) re-ran the verifier -- `VERDICT: PASS`, exit 0, confirming full restoration with zero residual cascade rows (`concept_transition_log` `parent_cascade` count still 0).
- **Files modified:** none (live-data test only, fully reverted)
- **Verification:** Exit codes recorded above; live database confirmed restored to its pre-test state.
- **Committed in:** N/A (no code change; test methodology documented in this Summary and in the Task 2 commit message)

---

**Total deviations:** 3 auto-fixed (all Rule 1 - bugs surfaced by real live data the plan's snapshot didn't fully characterize, or by an unverified test methodology in the plan text)
**Impact on plan:** All three fixes were necessary for migration 284 to apply at all (deviation 1), for its own acceptance criteria to remain literally true (deviation 2), and for Task 2's acceptance criterion ("a verifier that cannot fail is not a verifier") to be actually demonstrated rather than merely asserted (deviation 3). No scope creep -- migration 284 remains DATA-only, zero schema changes, zero application-code changes.

## Issues Encountered
None beyond the three deviations above, all resolved during execution.

## User Setup Required

None - no external service configuration required. Migration was applied directly to the live `indicagent` database as part of Task 1 (per this project's convention: migrations are applied by hand, no `schema_migrations` tracking table).

## Next Phase Readiness
- `domain='feature'` is fully materialized in the concept tables with provable, re-checkable parity against `feature_registry`, including multi-parent lineage and the complete transition history (2 orphaned rows included via tombstones) -- the preconditions for Plan 08's eventual `DROP TABLE feature_registry` / `DROP TABLE feature_transition_log` are met at the data layer.
- `scripts/ops/alpha/ops_concept_feature_migration_verify.py` is live and proven-failing; Plan 06 (consumer repoint) and Plan 08 (drop + pre-drop gate) can both re-run it directly.
- `feature_registry` remains the sole live authority for the feature lifecycle until Plan 06 cuts the writers over -- this plan changed zero application code, exactly as scoped.
- `production/migrations/285_...` is the next free migration number.

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*

## Self-Check: PASSED

- FOUND: production/migrations/284_concept_registry_feature_domain_seed.sql
- FOUND: scripts/ops/alpha/ops_concept_feature_migration_verify.py
- FOUND: c195f16d (Task 1 commit)
- FOUND: fd7228fd (Task 2 commit)
