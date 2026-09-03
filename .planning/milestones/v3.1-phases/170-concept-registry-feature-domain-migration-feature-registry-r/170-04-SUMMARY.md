---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 04
subsystem: database
tags: [postgresql, psycopg, concept_registry, feature_registry, ic_engine, lifecycle-governance]

requires:
  - phase: 170-02
    provides: async ConceptRegistryService FDR-aware promotion path (decide_comparison_action, record_comparison_outcome, GateState.fdr_required)
  - phase: 170-03
    provides: domain='feature' fully materialized in concept_registry/concept_gate/concept_parent, parity verifier (ops_concept_feature_migration_verify.py)
provides:
  - "ConceptRegistryService.load_sync/record_transition_sync/advance_shadow_counters_sync/is_promotion_eligible/get_all_concepts -- the synchronous psycopg lifecycle path ic_engine's no-event-loop context needs"
  - "FeatureRegistryService's CAS + counter-reset + operator-only-deprecated + fail-closed-FDR semantics ported onto the concept tables, with none of its dead accessors (get_active_features/get_feature/get_status/get_ic_sharpe_gate) carried forward"
  - "15 behavioural tests against real indicagent_test proving the ported semantics, replacing the coverage tests/unit/intelligence/test_feature_registry_service.py loses when it is deleted in Plan 08"
affects: [170-06, 170-07, 170-08]

tech-stack:
  added: []
  patterns:
    - "Sync psycopg lifecycle path sits alongside an existing stateless async service on the same class -- one governance service per registry, not a second class or module, keeps the invariant-1 access-control surface auditable in one place"
    - "conn.transaction() (never bare `with conn:`) for a caller-owned connection reused across many transitions within one process -- psycopg (unlike psycopg2) closes the connection on a bare `with conn:` exit"
    - "Fail-closed FDR guard resolves its input from an in-memory cache when loaded, else a direct DB read inside the same transaction -- never silently skips a governance check just because the cache is cold"

key-files:
  created:
    - tests/integration/test_concept_registry_sync_lifecycle.py
  modified:
    - src/intelligence/concept_registry_service.py

key-decisions:
  - "record_transition_sync's FDR guard executes inside `with conn.transaction():` before the CAS UPDATE, mirroring record_comparison_outcome's async guard placement -- returning False from inside an open transaction with no writes yet issued commits an empty transaction, matching the async path's documented behavior"
  - "New tests live under tests/integration/ (not tests/unit/) because the DB fixture that replays migrations 283/284 into indicagent_test (migrated_test_database, session-scoped autouse) only exists in tests/integration/conftest.py -- these are real psycopg-driver tests, not FakeConn stubs"
  - "is_promotion_eligible's tests seed the in-memory cache directly (no DB) since the method is a pure Python predicate over self._concepts -- matches the original FeatureRegistryService test style exactly"

requirements-completed: [S-2, L-5, L-6]

duration: 15min
completed: 2026-08-04
---

# Phase 170 Plan 04: ic_engine Sync Lifecycle Path Summary

**`ConceptRegistryService` gains a synchronous psycopg lifecycle path (load_sync/record_transition_sync/advance_shadow_counters_sync/is_promotion_eligible/get_all_concepts) with `FeatureRegistryService`'s CAS/counter-reset/operator-only-deprecated/fail-closed-FDR semantics ported exactly, proven by 15 tests against a real database -- ic_engine and ensemble_trainer remain untouched, still calling `FeatureRegistryService` until Plan 06's cutover.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-04T13:10:46-04:00
- **Completed:** 2026-08-04T13:21:48-04:00
- **Tasks:** 2
- **Files modified:** 2 (1 modified, 1 new)

## Accomplishments
- Added the four public sync methods plus `get_all_concepts` to `ConceptRegistryService`, sitting alongside the pre-existing async `record_comparison_outcome` path without disturbing it -- one class, both drivers (asyncpg for `ensemble_strategy`, psycopg for `feature`)
- Ported `FeatureRegistryService.record_transition_sync`'s optimistic-lock CAS, the Fable-N1 shadow-counter reset on demotion, and the operator-only-deprecated guard verbatim in spirit, adapted to the two-table split (status lives on `concept_registry`, counters on `concept_gate`) while preserving single-transaction atomicity
- Added the sync-side L-6 fail-closed FDR promotion guard (todo 118), mirroring Plan 02's async guard: a promotion to `active` for a concept whose `concept_gate.fdr_required` is true is refused unless `fdr_passed is True`, resolved from the in-memory cache when loaded or a direct DB read when cold -- never silently skipped
- Wrote 15 tests (11 named scenarios, 4 of them parametrized) against real `indicagent_test` via psycopg, closing every coverage gap `tests/unit/intelligence/test_feature_registry_service.py` will leave when deleted in Plan 08 (mapping documented in the new test module's docstring)
- Confirmed zero dead accessors carried forward (`get_active_concepts`/`get_concept`/`get_status` do not exist) and zero cross-domain import (`FeatureVector` does not appear in `concept_registry_service.py`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the sync psycopg lifecycle path to ConceptRegistryService** - `d7a607e5` (feat)
2. **Task 2: Behavioural tests for the sync lifecycle path** - `09657ed3` (test)

## Files Created/Modified
- `src/intelligence/concept_registry_service.py` - added `_TransitionNoOp` sentinel, `_AUTOMATED_SYNC_REASONS`/`_VALID_TRANSITION_REASONS` constants, 6 sync-path SQL constants, `ConceptRegistryService.__init__` (new -- the class was previously stateless), and 5 new methods: `load_sync`, `_fdr_required_sync` (private helper), `record_transition_sync`, `advance_shadow_counters_sync`, `is_promotion_eligible`, `get_all_concepts`. `record_comparison_outcome` (async) untouched.
- `tests/integration/test_concept_registry_sync_lifecycle.py` (new) - 15 tests against real `indicagent_test`, `pytestmark = [pytest.mark.integration, pytest.mark.requires_db]`, cleans up its own throwaway `_t170sync_*` rows in fixture teardown.

## Decisions Made
See `key-decisions` in frontmatter. Summary: the FDR guard's transaction placement mirrors the async path exactly (return-from-open-transaction commits an empty no-op transaction); the new tests had to live under `tests/integration/` rather than `tests/unit/` because only that directory's `conftest.py` replays migrations 283/284 into a real database; `is_promotion_eligible`'s tests seed the cache directly since the method never touches the DB.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree missing `.venv`, blocking both interactive linting and the pre-commit hook**
- **Found during:** Task 1, first commit attempt
- **Issue:** This worktree has no `.venv` (gitignored, never copied into a fresh worktree checkout -- a known class of issue, see project memory `feedback_gsd_worktree_venv_missing.md`). The pre-commit hook resolves `RUFF_BIN`/black relative to `git rev-parse --show-toplevel`, which inside a worktree resolves to the worktree root, not the main repo -- so both tools were reported "not found" and the commit was blocked. The hook's log file write also failed because `logs/` did not yet exist in the worktree.
- **Fix:** Created `logs/` (empty, needed only for the hook's own log file) and symlinked `.venv -> /home/bg/dev/indicagent/.venv` (the main repo's real virtualenv) into the worktree root. `.venv` is gitignored, so the symlink itself is invisible to git and was never staged.
- **Files modified:** none tracked (the symlink and `logs/` directory are both gitignored/untracked, environment-only).
- **Verification:** Both commits' pre-commit hooks subsequently ran ruff/black successfully and passed all 9 checks.
- **Committed in:** N/A (untracked environment fix, not a code change).

**2. [Rule 1 - Bug, documentation-only] Plan's literal `grep -c "with conn:" == 0` acceptance check has a known false-positive against precedent**
- **Found during:** Task 1, acceptance-criteria verification pass
- **Issue:** The plan's action text explicitly instructs carrying the "never a bare `with conn:`" warning comment across from `feature_registry_service.py` "verbatim." Doing so means the docstrings for `record_transition_sync`/`advance_shadow_counters_sync` literally contain the substring `with conn:` (inside backticks, as prose, never as code). `grep -c "with conn:" src/intelligence/concept_registry_service.py` therefore returns 3, not 0 -- but `grep -c "with conn:" src/intelligence/feature_registry_service.py` (the file this plan explicitly ports from) *also* returns 3, for the identical reason. Manually confirmed all 3 occurrences in the new file are prose inside docstrings; zero actual code uses a bare `with conn:` context manager (verified: every `with conn.` use is `conn.transaction()` or `conn.cursor()`).
- **Fix:** No code change -- kept the docstring warnings verbatim per the plan's own explicit instruction, consistent with established precedent in the file this plan was told to port from. Documenting this here rather than silently reporting a passing grep count that would be inaccurate.
- **Files modified:** none.
- **Verification:** `grep -c "conn\.transaction()\|conn\.cursor()" ` inspection confirms zero bare `with conn:` usages in actual code; the 3 grep hits are all inside triple-quoted docstrings.
- **Committed in:** N/A (no fix needed; behavior matches instructed precedent).

---

**Total deviations:** 2 (1 blocking-environment fix, 1 documentation-only false-positive noted for the record)
**Impact on plan:** Neither affects correctness or scope. The `.venv` symlink is a pure environment fix required to run the mandated pre-commit hooks at all; the grep false-positive is inherited from the exact file the plan instructs porting from verbatim, and was verified not to reflect any actual bare-`with conn:` code.

## Issues Encountered
None beyond the two items above, both resolved during execution.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The synchronous lifecycle capability now exists on `ConceptRegistryService`, proven against real data, but **ic_engine.py and ensemble_trainer.py remain completely unchanged** -- verified via `git diff --name-only HEAD~2 HEAD -- services/ic_engine.py services/ensemble_trainer.py` returning empty. `FeatureRegistryService` remains the sole live authority for the feature lifecycle.
- `scripts/ops/alpha/ops_concept_feature_migration_verify.py` still reports `VERDICT: PASS` (11/11 checks) against live `indicagent` -- this plan wrote zero data to the live database.
- Plan 06 (consumer repoint) can now call `load_sync`/`record_transition_sync`/`advance_shadow_counters_sync`/`is_promotion_eligible`/`get_all_concepts` directly, matching the exact call shapes `ic_engine.py`'s `_apply_feature_transitions` (lines 3881-3998) already uses against `FeatureRegistryService` today.
- Plan 08's eventual deletion of `tests/unit/intelligence/test_feature_registry_service.py` will not silently lose coverage: every behavior it proves for `record_transition_sync`/`advance_shadow_counters_sync`/`is_promotion_eligible` now has an equivalent proven against the concept tables in `tests/integration/test_concept_registry_sync_lifecycle.py`.

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*

## Self-Check: PASSED

- FOUND: src/intelligence/concept_registry_service.py
- FOUND: tests/integration/test_concept_registry_sync_lifecycle.py
- FOUND: d7a607e5 (Task 1 commit)
- FOUND: 09657ed3 (Task 2 commit)
