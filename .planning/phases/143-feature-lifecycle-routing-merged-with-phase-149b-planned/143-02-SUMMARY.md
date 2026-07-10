---
phase: 143-feature-lifecycle-routing-merged-with-phase-149b-planned
plan: 02
subsystem: database
tags: [postgres, psycopg2, feature-registry, lifecycle-routing, apr]

# Dependency graph
requires:
  - phase: 143-01
    provides: regime_writer occupation gate / churn feature groundwork (independent track, same phase)
provides:
  - "feature_registry.consecutive_shadow_passes + observations_since_demotion columns"
  - "alpha.decay.recovery_min_passes APR key (default 2)"
  - "FeatureRegistryService.record_transition_sync — blocking, optimistic-locked, cache-coherent transition writer callable from ic_engine's psycopg2 context"
  - "FeatureRegistryService.advance_shadow_counters_sync — the sole non-reset counter mutation path"
  - "FeatureRegistryService.is_promotion_eligible — evidence-only shadow_only -> active promotion predicate"
  - "feature_ic_scores with is_decaying/decay_detected_at/recovery_eligible_at dropped"
affects: [143-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sync psycopg2 `with conn:` transaction mirroring an existing async asyncpg transaction body, for callers with no event loop"
    - "Optimistic locking via `WHERE status = %s` (from_status) + rowcount==0 no-op, using an internal sentinel exception to force rollback without inserting a log row"
    - "In-memory cache mutated only after a successful commit, never speculatively"

key-files:
  created:
    - production/migrations/216_feature_registry_lifecycle_columns.sql
    - production/migrations/217_drop_dead_feature_ic_scores_columns.sql
    - .planning/phases/143-feature-lifecycle-routing-merged-with-phase-149b-planned/deferred-items.md
  modified:
    - src/intelligence/feature_registry_service.py
    - tests/unit/intelligence/test_feature_registry_service.py

key-decisions:
  - "pre_shadow_weight dropped entirely (cross-AI review HIGH finding 2): ensemble_trainer.py recomputes every weight from scratch each run with no warm-start read, so a seed column would be written to and never read. Promotion is the status flip alone."
  - "Counter reset is unconditional on to_status == 'shadow_only', not conditional on prior counter values, closing the Fable N1 oscillation gap: promote -> re-demote -> single-passing-run would otherwise instantly re-promote."
  - "Demotion has no consecutive-fail counter — it stays the single-run materiality gate Plan 03 will implement; only the (already-planned) recovery side gets counters."

requirements-completed: [LIFECYCLE-01]

# Metrics
duration: 20min
completed: 2026-07-10
---

# Phase 143 Plan 02: feature_registry lifecycle routing (sync transition writer + counters) Summary

**Synchronous, optimistic-locked `record_transition_sync` on `FeatureRegistryService` plus two new `feature_registry` counter columns, giving ic_engine's Plan 03 hook a blocking, rerun-safe write path into the one authoritative lifecycle state machine — no `pre_shadow_weight`, no parallel state machine.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-10T08:05:00-04:00 (approx, from worktree setup)
- **Completed:** 2026-07-10T08:25:39-04:00
- **Tasks:** 2 (Task 2 executed as TDD: RED then GREEN)
- **Files modified:** 4 (2 new migrations, 1 service file, 1 test file) + 1 deferred-items log

## Accomplishments
- Migration 216: `consecutive_shadow_passes` (int, default 0) + `observations_since_demotion` (bigint, default 0) added to `feature_registry`, plus the `alpha.decay.recovery_min_passes` APR key (default 2) — companion to the existing `alpha.decay.recovery_min_observations` (2000) from migration 161. No `pre_shadow_weight`, no `consecutive_shadow_fails`, no CHECK constraint change.
- Migration 217: dropped the three dead `feature_ic_scores` columns (`is_decaying`, `decay_detected_at`, `recovery_eligible_at`) per D3 — confirmed never written by any live INSERT/UPDATE.
- `record_transition_sync(conn, feature_name, from_status, to_status, reason, ...)`: blocking psycopg2 transaction (`with conn:`) mirroring the existing async `_write_transition_record`'s two-statement body (UPDATE `feature_registry` + INSERT `feature_transition_log`), but with an optimistic `WHERE status = from_status` lock on the UPDATE. `rowcount == 0` rolls back the whole transaction (no orphan log row) and returns `False` — a safe no-op on rerun. Automated reasons (`ic_promotion`/`ic_demotion`) targeting `to_status='deprecated'` raise `ValueError` before any write. Every `active -> shadow_only` demotion resets both counters to 0 in the *same* UPDATE statement (Fable review finding N1).
- `advance_shadow_counters_sync(conn, feature_name, passed, new_observations)`: the sole counter-advance path outside the reset — increments `consecutive_shadow_passes` on a pass / resets to 0 on a fail, always adds `new_observations`, in one transaction.
- `is_promotion_eligible(feature_name, recovery_min_observations, recovery_min_passes)`: pure evidence-only predicate reading the in-memory cache, both floors caller-supplied (no hardcoded 2/2000, no calendar/date input).
- `_LOAD_QUERY` extended to cache both new counter columns at `load_sync()` time.
- 18 new unit tests (`TestRecordTransitionSync`, `TestAdvanceShadowCountersSync`, `TestIsPromotionEligible`) added via RED-then-GREEN TDD, using a hand-rolled fake psycopg2 `_FakeConn`/`_FakeCursor` pair that mirrors real `with conn:` commit/rollback semantics — no real DB needed for the unit layer.

## Task Commits

Each task was committed atomically:

1. **Task 1: Registry lifecycle-column migration + drop dead decay columns** - `2d04f89a` (feat)
2. **Task 2 RED: failing tests for record_transition_sync + counter methods** - `e57f8e20` (test)
3. **Task 2 GREEN: implement record_transition_sync + counter helpers** - `a0e35756` (feat)
4. **Deviation log: pre-existing test_feature_factory failure** - `fdeb5a8e` (docs)

_TDD tasks may have multiple commits (test → feat); no refactor commit was needed — the GREEN implementation was clean on first pass._

## Files Created/Modified
- `production/migrations/216_feature_registry_lifecycle_columns.sql` - adds `consecutive_shadow_passes`/`observations_since_demotion` columns + `alpha.decay.recovery_min_passes` APR key; applied and re-applied idempotently against the live DB
- `production/migrations/217_drop_dead_feature_ic_scores_columns.sql` - drops the three dead decay columns from `feature_ic_scores`; applied and re-applied idempotently
- `src/intelligence/feature_registry_service.py` - adds `record_transition_sync`, `advance_shadow_counters_sync`, `is_promotion_eligible`, and extends `_LOAD_QUERY`; existing async `record_transition`/`_write_transition_record` untouched (diff confirms only additive changes plus the one `_LOAD_QUERY` line edit)
- `tests/unit/intelligence/test_feature_registry_service.py` - 18 new tests across 3 new test classes plus a fake psycopg2 connection/cursor test double
- `.planning/phases/143-feature-lifecycle-routing-merged-with-phase-149b-planned/deferred-items.md` - new file logging one pre-existing, unrelated full-suite test failure

## Decisions Made
- **No `pre_shadow_weight`** (review-driven, confirmed against live code): `services/ensemble_trainer.py` is the sole `ensemble_weights` writer and recomputes every weight from scratch each run from that run's `feature_ic_scores` rows — no prior-weight read anywhere in the file. A seed scalar would be written to a column nothing reads. Promotion is the status flip alone; the next `ic_engine` run stamps `feature_status_at_eval='active'` and the next `ensemble_trainer` run naturally recomputes.
- **Unconditional counter reset on every `active -> shadow_only` transition** rather than only on "first" demotion, per Fable review N1 (HIGH): without this, a feature that already earned promotion once and decays a second time would carry pre-satisfied counters and re-promote after a single passing run, defeating the evidence bar.
- **Optimistic lock via `WHERE status = from_status` + `rowcount == 0` no-op**, implemented with an internal `_TransitionNoOp` sentinel exception caught after the `with conn:` block rolls back — keeps the no-op path indistinguishable from "never attempted" at the DB level while still returning a clear boolean to the caller.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing `.venv` in worktree — symlinked to main repo's venv**
- **Found during:** Task 1 verification (running `.venv/bin/pytest`)
- **Issue:** This worktree has no `.venv/` directory (git worktrees don't carry the Python venv); pre-commit hooks and the plan's own verify commands reference `.venv/bin/{pytest,ruff,black}` relative to repo root, which resolved to a missing path and blocked both test execution and the commit's ruff/black pre-commit gates.
- **Fix:** Created `.venv` as a symlink to `/home/bg/dev/indicagent/.venv` (the main repo's venv) — the same pattern already in use by a sibling worktree (`interaction-primitives-partial-ic-pilot`). `.venv` is gitignored, so this is untracked and does not appear in any commit diff.
- **Files modified:** none (symlink only, gitignored)
- **Verification:** `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/black` all resolve and run correctly after the symlink; pre-commit hooks pass on both task commits.

**2. [Rule 3 - Blocking / scope boundary] Worktree HEAD was stale relative to `main`**
- **Found during:** Startup branch check (mandatory first action)
- **Issue:** The worktree's branch HEAD (`9aed7e48`) predated `main`'s tip (`37a52320`, the migration-renumbering commit called out in the dispatch) and was not an ancestor of it — the worktree had branched before several other phases' work (142B waves 1/2, the renumbering commit) landed on `main`. Continuing from the stale base risked migration-number collisions (216/217 vs. whatever was actually free) and missing context from intervening commits.
- **Fix:** Per the `<worktree_branch_check>` step's explicit instruction ("If `merge-base HEAD 37a52320` != `37a52320`, run `git reset --hard 37a52320`"), reset the worktree branch to `37a52320` before any work began. This is the one sanctioned exception to the destructive-git-prohibition's `git reset --hard` ban (inside the startup branch-check step only). Working tree was clean at the time (verified via `git status --short` before resetting).
- **Files modified:** none (branch pointer only, prior to any task work)
- **Verification:** `ls production/migrations/ | sort | tail -5` post-reset confirmed 215 as the highest existing migration, matching the plan's stated 216/217 numbering exactly — no renumbering needed.

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking infrastructure/setup issues, zero application-logic deviations)
**Impact on plan:** Both fixes were prerequisites for executing the plan at all (missing tooling, stale git base) rather than changes to the plan's design or scope. The plan's own logic (migrations, service methods, tests) was implemented exactly as specified with no scope creep.

## Issues Encountered
- Full `tests/unit/` suite run surfaced one pre-existing, unrelated failure: `tests/unit/test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`. Confirmed via `git show 37a52320:tests/unit/test_feature_factory.py | diff` that the test file is byte-identical to its state before this plan's commits — not touched by, or dependent on, anything in this plan. Logged to the new `deferred-items.md` per SCOPE BOUNDARY rather than fixed inline. All tests in the plan's own scope (`tests/unit/intelligence/test_feature_registry_service.py`, 34 tests) are green, and the full-suite run is otherwise green (5670 passed, 42 skipped, 1 unrelated failure).

## User Setup Required

None - no external service configuration required. Both migrations were applied directly against the live local PostgreSQL/TimescaleDB instance (`indicagent` DB) as part of task verification, and re-applied a second time to confirm idempotency (`ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS` / `ON CONFLICT DO NOTHING`).

## Next Phase Readiness
- Plan 03 (ic_engine post-run hook) can now call `record_transition_sync` for demotion (materiality-gated, single-run) and promotion (`is_promotion_eligible` gate), and `advance_shadow_counters_sync` after each corpus run against `shadow_only` features, reading both APR floors via `ConfigService.get_sync("alpha.decay.recovery_min_passes")` / `("alpha.decay.recovery_min_observations")`.
- No blockers. The cascade trigger (`trg_cascade_parent_deprecation`, migration 172) is unchanged and will not fire on `shadow_only` demotions — it only fires on transitions *into* `deprecated`, which automated paths cannot reach.

---
*Phase: 143-feature-lifecycle-routing-merged-with-phase-149b-planned*
*Completed: 2026-07-10*
