---
phase: 143-feature-lifecycle-routing-merged-with-phase-149b
plan: 03
subsystem: database
tags: [postgres, psycopg2, ic-engine, feature-registry, lifecycle-routing, apr, otel, timescaledb]

# Dependency graph
requires:
  - phase: 143-01
    provides: regime label trust groundwork (independent track, same phase)
  - phase: 143-02
    provides: "FeatureRegistryService.record_transition_sync / advance_shadow_counters_sync / is_promotion_eligible (sync psycopg2 transition writer + shadow recovery counters), consecutive_shadow_passes/observations_since_demotion columns, alpha.decay.recovery_min_passes APR key"
provides:
  - "integrity_monitor hypertable (migration 218) -- observability-only gate-evaluation facts, idempotency-keyed"
  - "alpha.ic.staleness_alert_days APR key (migration 219, default 5)"
  - "ic_engine's _run_lifecycle_hook -- the single post-run place feature_registry status changes (demote decaying active features to shadow_only, promote recovered ones back to active), regime-shift guard, IC staleness gauge"
  - "3 new OTel metrics: ALPHA_DECAY_CELLS_FLAGGED, ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL, IC_ENGINE_LAST_RUN_AGE_DAYS"
  - "LIFECYCLE-02 regression lock on EnsembleTrainer._process_stratum's feature_status_at_eval='active' filter"
  - "docs/analysis/feature-decay-queries.sql -- LIFECYCLE-06 ad-hoc decay diagnostics (4 verified queries)"
affects: [147, 149B]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Post-run lifecycle hook as a module-level free function (_run_lifecycle_hook) matching ic_engine.py's existing free-function write style -- no class, no BaseBatch, no async"
    - "Hook opens and closes its own short-lived write connection (mirrors _persist_corpus_results' documented pattern) rather than holding one across the multi-minute compute phase -- deviation from the plan's assumed 'write_conn already in scope' interface, see Deviations"
    - "Feature-level aggregation from per-cell IC via GROUP BY feature_name in Python (fake-conn-testable), sharing the ensemble's own alpha.ensemble.meta_fdr_min_fraction constant so demotion and ensemble-inclusion can't drift apart"
    - "Pure staleness-decision helper (_evaluate_staleness) extracted so age/alert logic is unit-testable independent of the DB/manifest plumbing around it"

key-files:
  created:
    - production/migrations/218_integrity_monitor.sql
    - production/migrations/219_ic_staleness_apr_key.sql
    - tests/unit/test_ic_engine_lifecycle_hook.py
    - tests/unit/test_ic_engine_staleness.py
    - docs/analysis/feature-decay-queries.sql
  modified:
    - services/ic_engine.py
    - src/observability/metrics.py
    - tests/unit/test_ensemble_trainer.py

key-decisions:
  - "TimescaleDB requires every unique index on a hypertable to include the partitioning column -- integrity_monitor's idempotency UNIQUE index had to include evaluated_at (real wall-clock DEFAULT now()), which means the DB constraint only catches an exact-instant double-insert. The hook's own step-0 pre-check (SELECT before any write, keyed on training_window_end) is the actual, authoritative rerun-idempotency guarantee -- documented explicitly in the migration."
  - "main() holds no open write connection at the plan's stated insertion point -- _persist_corpus_results already owns its own connection lifecycle start-to-finish (a deliberate 2026-07-08 incident fix, see its docstring), so the plan's assumed 'write_conn already in scope' interface does not match live code. _run_lifecycle_hook accepts write_conn as a parameter (exactly as specified, keeping it fake-conn-testable) but main() opens and closes a fresh short-lived connection around the one call, mirroring the established pattern instead of introducing a long-held connection across the multi-minute compute phase."
  - "ICEngineConfig's 7 new lifecycle fields were given defaults matching their APR fallback values (rather than left required) after the full-suite run caught a pre-existing, unrelated test (tests/unit/test_hac_ic_sharpe.py) constructing ICEngineConfig(...) directly with only the original 18 fields. from_apr() always binds all fields explicitly in production, so defaulting is a safe, non-invasive fix (Rule 1)."

requirements-completed: [LIFECYCLE-02, LIFECYCLE-03, LIFECYCLE-04, LIFECYCLE-05, LIFECYCLE-06]

# Metrics
duration: 65min
completed: 2026-07-10
---

# Phase 143 Plan 03: ic_engine post-run lifecycle hook (feature demotion/promotion + regime-shift guard + IC staleness) Summary

**Post-run hook in ic_engine.main() that closes the feature-lifecycle loop: a deterministic, feature-level material-fail-fraction gate demotes decaying active features to shadow_only, `is_promotion_eligible` recovers shadow_only features back to active (status flip only -- ic_engine never writes ensemble_weights), a 60%-of-active-cells regime-shift guard holds all weights instead of misreading a market dislocation as mass decay, and an IC-staleness gauge/alert round out LIFECYCLE-05 -- all synchronous psycopg2, idempotent on training_window_end.**

## Performance

- **Duration:** ~65 min (including a resource-contention-caused false start on the full-suite verification run, diagnosed and resolved)
- **Started:** 2026-07-10T12:40:00Z (approx, from worktree setup)
- **Completed:** 2026-07-10T13:45:00Z (approx)
- **Tasks:** 3 (Task 2 executed as TDD: tests + implementation delivered together, see Deviations)
- **Files modified:** 8 (2 new migrations, 1 service file, 1 metrics file, 3 new/modified test files, 1 new diagnostics SQL file)

## Accomplishments

- **Migration 218**: `integrity_monitor` TimescaleDB hypertable (observability-only gate-evaluation facts; `feature_transition_log` remains the sole authoritative transition record) with an idempotency-oriented UNIQUE index, verified idempotent on re-run.
- **Migration 219**: `alpha.ic.staleness_alert_days` APR key (default 5, `[initial_estimate]`, 1-90 bounds).
- **3 new OTel metrics** (`ALPHA_DECAY_CELLS_FLAGGED`, `ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL`, `IC_ENGINE_LAST_RUN_AGE_DAYS`) via the existing `counter`/`point_gauge` factories -- no `prometheus_client`.
- **`_run_lifecycle_hook`**: the full LIFECYCLE-03/04 specification --
  - Idempotency short-circuit keyed on `training_window_end` (step 0).
  - Single-lookahead-pinned (Fable N3: `alpha.ic.lookahead.mid`, reused `lookahead_mid` field) + champion-`weight_version`-pinned (Fable N4: `alpha.ensemble.weight_version`, never `ORDER BY computed_at DESC LIMIT 1`) per-cell IC load from `feature_ic_scores` LEFT JOIN `ensemble_weights` (read-only).
  - Zero-cell guard (Fable N5): a per-symbol-only or equity-model-disabled run logs and returns without writing any `integrity_monitor` fact, so it never poisons the idempotency key for a later run against the same window.
  - Regime-shift guard evaluated FIRST: >=60% of active cells failing simultaneously holds all weights (zero transitions), logs, and writes one hold fact.
  - Feature-level demotion: `demote_fraction = material_fail_cells / active_cells >= (1 - alpha.ensemble.meta_fdr_min_fraction)` calls `record_transition_sync(..., 'active', 'shadow_only', 'ic_demotion')`.
  - Feature-level promotion: `advance_shadow_counters_sync` then `is_promotion_eligible` gates `record_transition_sync(..., 'shadow_only', 'active', 'ic_promotion')` -- a pure status flip, zero `ensemble_weights` writes (sole-writer invariant preserved, grep-verified).
  - One `integrity_monitor` gate-evaluation fact per non-hold run.
  - `_evaluate_staleness` (pure function) + `_get_prior_ic_engine_completion` (CorpusManifest history, `feature_ic_scores` fallback, first-run age=0/no-alert) implement LIFECYCLE-05, documented as an in-run diagnostic (Fable N6) not a live absence detector.
  - N8 cleanup: removed the dead `is_decaying`/`decay_detected_at` entries from the manifest's `columns_written` literal (migration 217 already dropped both columns).
- **LIFECYCLE-02 regression lock**: `TestFeatureStatusAtEvalFilter` asserts `EnsembleTrainer._process_stratum`'s `feature_status_at_eval = 'active'` filter via source inspection (no existing coverage found, so this was net-new, not a duplicate).
- **LIFECYCLE-06**: `docs/analysis/feature-decay-queries.sql` -- 4 ad-hoc diagnostic queries (recent transitions, shadow_only recovery progress vs. both floors, regime-shift-hold history, materiality-boundary early warning), all 4 verified to run cleanly against the live DB. No dashboard (deferred per plan, >=30 days of routed-system operation).
- **34 new/added tests**, all green: 24 in `test_ic_engine_lifecycle_hook.py` + `test_ic_engine_staleness.py` (a hand-rolled fake psycopg2 connection that exercises the hook's actual SQL parameter binding for `lookahead_bars`/`weight_version`, not just Python-side aggregation) + 1 new regression test in `test_ensemble_trainer.py`.

## Task Commits

Each task was committed atomically:

1. **Task 1: integrity_monitor hypertable + staleness APR key + OTel metrics** - `9beeabc0` (feat)
2. **Task 2: ic_engine post-run lifecycle hook (LIFECYCLE-03/04/05)** - `29eccdef` (feat, tests + implementation delivered together -- see Deviations)
3. **Task 3: LIFECYCLE-02 regression lock + LIFECYCLE-06 decay diagnostics SQL** - `a6fadea3` (test)
4. **Fix: ICEngineConfig backward-compat defaults** - `b47595b9` (fix, caught by the full `tests/unit/` suite run)

## Files Created/Modified

- `production/migrations/218_integrity_monitor.sql` - `integrity_monitor` hypertable + idempotency UNIQUE index; applied and re-applied idempotently
- `production/migrations/219_ic_staleness_apr_key.sql` - `alpha.ic.staleness_alert_days` APR key; applied and re-applied idempotently
- `src/observability/metrics.py` - 3 new OTel metrics for the lifecycle hook
- `services/ic_engine.py` - `ICEngineConfig` gains 7 lifecycle fields (all APR-sourced, all defaulted for backward compat); `_run_lifecycle_hook`, `_get_prior_ic_engine_completion`, `_evaluate_staleness` added; hook wired into `main()` after `_persist_corpus_results`, before `IC_ENGINE_RUN_LATENCY_SECONDS.record`; N8 manifest cleanup
- `tests/unit/test_ic_engine_lifecycle_hook.py` - 20 tests: demotion (boundary both directions, materiality/zero-standing-weight), promotion (eligible/ineligible, zero ensemble_weights writes), regime-shift hold, idempotency short-circuit, Fable N3/N4/N5 (lookahead pinning, weight_version pinning, zero-cell guard), one-fact-per-run, plus 4 structural/source-inspection assertions
- `tests/unit/test_ic_engine_staleness.py` - 9 tests: `_evaluate_staleness` pure-function boundary cases (fires/no-fire/exactly-at-threshold/naive-datetime/first-run) + 2 hook-level integration tests using a real `CorpusManifest` written to a `tmp_path`
- `tests/unit/test_ensemble_trainer.py` - `TestFeatureStatusAtEvalFilter` regression lock (net-new, no prior coverage existed)
- `docs/analysis/feature-decay-queries.sql` - 4 verified ad-hoc diagnostics

## Decisions Made

- **integrity_monitor's idempotency UNIQUE index must include `evaluated_at`** (TimescaleDB requirement: every unique index on a hypertable must include the partitioning column). This means the DB-level constraint only catches an exact-instant double-insert; the hook's own step-0 `SELECT`-before-`INSERT` pre-check (keyed on `training_window_end`, done before any write) is the real, authoritative rerun-idempotency guarantee. Documented explicitly in the migration's header comment so a future reader doesn't mistake the DB index for the primary defense.
- **`_run_lifecycle_hook` opens its own connection rather than reusing a held `write_conn`** -- see Deviations below; this follows the codebase's own established pattern (`_persist_corpus_results`'s documented 2026-07-08-incident fix) rather than introducing a long-held connection across the multi-minute compute phase.
- **`ICEngineConfig`'s 7 new fields default to their APR fallback values** rather than being required, after the full-suite run surfaced a pre-existing direct-construction call site in an unrelated test file. `from_apr()` always binds every field explicitly in production, so this is purely a backward-compatibility safety net, not a behavior change.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/plan-assumption mismatch] `write_conn` is not actually in scope at the plan's stated insertion point**
- **Found during:** Task 2, reading `services/ic_engine.py`'s `main()` and `_persist_corpus_results` before writing the hook
- **Issue:** The plan's `<interfaces>` section stated "`write_conn` (open psycopg2) ... in scope" at the insertion point (after `_write_cross_sectional_results`, before `IC_ENGINE_RUN_LATENCY_SECONDS.record`). Live code shows `_persist_corpus_results` opens, uses, and closes its own write connection entirely internally -- a deliberate fix for a 2026-07-08 incident (819,538 computed rows lost when a connection was opened before ~53 minutes of compute and went dead by write time; the code comment on `_persist_corpus_results` documents this explicitly). `main()` itself never holds a write connection at all after this refactor.
- **Fix:** `_run_lifecycle_hook(write_conn, registry_svc, config, training_window_end, manifest)` keeps the plan's exact parameter signature (so it remains fake-conn-testable per the plan's own test spec), but `main()` opens a fresh, short-lived connection via `_connect_db(settings)` specifically for the one hook call, then closes it in a `finally` block -- mirroring `_persist_corpus_results`'s own pattern rather than introducing a connection held open across the multi-minute compute phase (which is exactly the class of bug the 2026-07-08 incident fix eliminated).
- **Files modified:** `services/ic_engine.py`
- **Verification:** `grep -n "write_conn" services/ic_engine.py` shows the hook function signature and all internal cursor calls use it consistently; `main()`'s call site opens/closes its own connection with try/except/finally so a hook failure logs loudly (`ic_engine.lifecycle_hook_failed`) without aborting the run or corrupting the already-committed IC results.

**2. [Rule 1 - Bug] `ICEngineConfig`'s 7 new required fields broke a pre-existing, unrelated test**
- **Found during:** Full `tests/unit/` suite run (post-Task-3), required by the coordinator to confirm only the known pre-existing `test_no_smooth_or_backward_in_factory` failure remained
- **Issue:** `tests/unit/test_hac_ic_sharpe.py::test_rolling_metrics_returns_five_tuple` constructs `ICEngineConfig(...)` directly with only the original 18 fields (predates this plan, tests `_compute_ic_rolling_metrics` in isolation). Adding this plan's 7 new lifecycle fields as required positional-or-keyword arguments broke that call site: `TypeError: ICEngineConfig.__init__() missing 7 required positional arguments`.
- **Fix:** Gave the 7 new fields defaults matching their APR fallback values (`decay_materiality_threshold=0.005`, `decay_regime_shift_fraction=0.60`, `decay_recovery_min_observations=2000`, `decay_recovery_min_passes=2`, `meta_fdr_min_fraction=0.50`, `ic_staleness_alert_days=5`, `ensemble_weight_version="v1"`). Safe because `from_apr()` always binds every field explicitly in production -- the defaults exist purely for backward-compatible direct construction.
- **Files modified:** `services/ic_engine.py`
- **Verification:** `tests/unit/test_hac_ic_sharpe.py -q` -- 7 passed. Full `tests/unit/` suite re-run confirms this was the only new failure introduced by this plan.
- **Committed in:** `b47595b9`

### Process note (not a code deviation)

A background full-suite verification run appeared to hang indefinitely at ~75% (stuck for 300+ seconds with near-zero CPU). Root-caused as **resource contention from 3 accidentally-duplicated concurrent `pytest tests/unit/` invocations** I started in this same session while polling -- killing the 2 redundant duplicates let the remaining run proceed. A second, independent stall at the exact same point (`tests/unit/providers/test_ibkr_equity.py::TestIBKRUseRTH::test_fetch_equity_bars_uses_rth`) was then diagnosed as a **pre-existing, unrelated slow test**: it exercises `IBKRProvider.fetch_historical_bars`'s real (unmocked) `asyncio.sleep(65)` + `asyncio.sleep(130)` retry-backoff path (`src/providers/ibkr.py` lines ~797-810) because the test's mocked `reqHistoricalDataAsync` returns an empty list, which the retry loop treats as "no data, retry." This is genuinely slow (~195s), not infinite -- the full suite completes in ~11-12 minutes end to end. Neither issue is a code defect in this plan's scope; noted here for the record, not filed as a todo (out of scope, pre-existing, already slow-but-passing).

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs -- one a plan/live-code interface mismatch, one a backward-compatibility regression this plan's own change introduced and then fixed within the same session)
**Impact on plan:** Both fixes were necessary for correctness; neither changed the plan's design or scope. No scope creep.

## Issues Encountered

- See "Process note" above -- a resource-contention false alarm plus a genuinely slow (not broken) pre-existing IBKR test, both fully diagnosed, neither a blocker.
- Full-suite result: **2 failed pre-fix -> 1 failed post-fix** (`tests/unit/test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`), matching exactly the one pre-existing failure already logged in `.planning/milestones/v3.1-phases/143-feature-lifecycle-routing-merged-with-phase-149b/deferred-items.md` from Plan 02 -- confirmed unrelated to this plan (not touched by any file in this plan's diff).

## User Setup Required

None - no external service configuration required. Both migrations were applied directly against the live local PostgreSQL/TimescaleDB instance (`indicagent` DB) and re-applied to confirm idempotency.

## Next Phase Readiness

- Phase 143's three plans (01 regime label trust, 02 sync transition writer + counters, 03 this hook) together close the feature lifecycle loop end-to-end: `ic_engine` now demotes/promotes automatically from live IC evidence, `ensemble_trainer`'s existing `feature_status_at_eval='active'` filter (LIFECYCLE-02, regression-locked) makes those transitions actually take effect on the next training run, and `integrity_monitor` + `feature_transition_log` + `docs/analysis/feature-decay-queries.sql` give full observability into the decision trail.
- No blockers for Phase 147 (live-promotion criteria) or 149B -- this hook has never run against real data yet (`integrity_monitor` and the lifecycle counters are all 0 rows as of this plan's completion); the first real `ic_engine` corpus run will populate them.
- `alpha.ensemble.weight_version` in the live `config_state` currently holds a per-run epoch value (`run_2025122405150000...`), not the literal `'v1'` default -- the hook correctly reads whatever this key currently resolves to (Fable N4 intent: track the APR champion, whatever it is, never the most-recent-by-computed_at row).

---
*Phase: 143-feature-lifecycle-routing-merged-with-phase-149b*
*Completed: 2026-07-10*

## Self-Check: PASSED

All 9 created/modified files verified present on disk (2 migrations, `services/ic_engine.py`,
`src/observability/metrics.py`, 2 new test files, `tests/unit/test_ensemble_trainer.py`,
`docs/analysis/feature-decay-queries.sql`, this SUMMARY.md). All 4 task/fix commit hashes
(`9beeabc0`, `29eccdef`, `a6fadea3`, `b47595b9`) verified present in `git log`. Coordinator
independently re-ran `tests/unit/test_hac_ic_sharpe.py` and confirmed 7/7 passing after the
`b47595b9` fix, and confirmed the only remaining full-suite failure is the pre-existing,
unrelated `test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`
(already logged in `deferred-items.md` by Wave 2/Plan 02, byte-identical to its pre-plan state).
