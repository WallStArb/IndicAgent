---
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
plan: 04
subsystem: database
tags: [ic_engine, fingerprint, apr, timescaledb, ops-script, empirical-validation]

# Dependency graph
requires:
  - phase: 162-01
    provides: "structurally-extracted, memory-bounded ic_engine.py compute functions the fingerprint hashes against"
  - phase: 162-02
    provides: "per-tf cross_sectional_bootstrap_threads (final OPERATIONAL-field shape 162-03/04 build on)"
  - phase: 162-03
    provides: "ic_cell_fingerprints table + whole-cell fingerprint gate wired into main() -- this plan's live-DB equivalence proof target, explicitly deferred to this plan by 162-03's own SUMMARY"
provides:
  - "scripts/ops/corpus/ops_ic_fingerprint_equivalence.py -- fresh-vs-fingerprint-skip equivalence harness + optional --drift-study diagnostic"
  - "production/migrations/252_ic_refresh_min_new_fraction.sql -- alpha.ic.refresh_min_new_fraction APR seed (0, disabled)"
  - "Live-DB empirical proof: the whole-cell fingerprint (162-03) captures everything that determines a cell's IC -- 5890 feature_ic_scores rows byte-identical between a forced --refresh run and the fingerprint-skip path, including bh_adjusted_p/passes_fdr, with computed_at unchanged confirming the skip path touched zero rows"
  - "Migrations 249-252 applied to the live production database for the first time (Phase 162 had only ever run in worktree sandboxes without DB access through 162-01/02/03)"
  - "Bug fix: _compute_upstream_watermark's market_regimes query used the wrong column name (regime instead of regime_label) -- would have crashed on its first real invocation"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ops-script pre-flight production-data-corruption guard: refuse to run a narrow-subset --refresh against any --training-window-end that already has real corpus rows, since cross-sectional cell membership is scoped only to the CLI --symbols list, not the full corpus universe"
    - "Auto-cleanup-on-success/leave-in-place-on-failure test-row lifecycle for a live-DB equivalence harness (dedicated throwaway training_window_end, deleted after a PASS, kept for inspection after a FAIL)"
    - "Two-signal diff (value divergence vs. skip-did-not-occur via computed_at) distinguishes a correctness failure from a throughput-only failure in the same harness"

key-files:
  created:
    - scripts/ops/corpus/ops_ic_fingerprint_equivalence.py
    - production/migrations/252_ic_refresh_min_new_fraction.sql
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_fingerprint.py

key-decisions:
  - "Equivalence check compares ALL feature_ic_scores value columns except computed_at as the completeness proof, then separately asserts computed_at is byte-unchanged as the 'did the skip actually happen' proof -- these are two different failure classes (wrong values vs. wasted recompute) and conflating them into one signal would lose diagnostic power"
  - "Column list (_PK_COLUMNS/_VALUE_COLUMNS/_FLOAT_COLUMNS/_SNAPSHOT_SQL) taken from the LIVE `\\d feature_ic_scores` schema, not migration 156's original DDL -- the live table has drifted substantially (ic_shrunk/regime_scope/partial_ic/sign_hit_rate/etc. added by later phases; is_decaying/decay_detected_at/recovery_eligible_at from 156 no longer exist; regime is now NOT NULL with a '_pooled' sentinel)"
  - "Added a production-data-corruption pre-flight guard beyond the plan's literal spec (Rule 2): --refresh's cross-sectional recompute scope is the CLI --symbols list, not the full corpus universe, so running against an already-populated training_window_end would silently narrow/overwrite real POOLED cells. The harness refuses unless --force, and auto-cleans up only rows it verified it owns"
  - "refresh_min_new_fraction classified COMPUTATIONAL in ic_engine.py's fingerprint field partition despite being currently unused/unwired -- same conservative-safety-margin precedent as sign_symmetric (162-03), so a future value change can never silently skip fingerprint invalidation once carry-forward behavior ships"

requirements-completed: [SC-1, SC-4]

# Metrics
duration: ~75min active work (includes live-DB discovery/fix of a real pre-existing bug and applying 4 backlogged migrations)
completed: 2026-07-23
---

# Phase 162 Plan 04: ic_engine Fresh-vs-Fingerprint-Skip Equivalence Harness Summary

**Live-DB equivalence harness proves 162-03's whole-cell fingerprint captures everything that determines a cell's IC (5890 rows byte-identical incl. bh_adjusted_p/passes_fdr, skip path confirmed via unchanged computed_at, run A 93.9s vs run B 3.0s), while also surfacing and fixing a real bug in the fingerprint's own watermark query and applying 4 backlogged migrations that had never touched the live database.**

## Performance

- **Duration:** ~75 min active work (longer than a typical 2-task plan because this is the phase's first live-DB execution point across all of 162-01/02/03/04 -- several real, previously-undiscoverable issues surfaced only once a live database was available)
- **Tasks:** 2/2 completed
- **Files modified:** 4 (2 modified, 2 created)

## Accomplishments

- `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py` -- runs a ~5-symbol subset through `ic_engine.py` twice against the same `--training-window-end` (run A `--refresh` forced-fresh, run B the normal fingerprint-skip path) and diffs `feature_ic_scores` on the full value set including `bh_adjusted_p`/`passes_fdr` (populated by a post-write BH-FDR backfill pass, not the per-cell write -- Risk 2's family-coherence requirement). Two independent failure signals: value divergence (wrong output) vs. `computed_at` drift (B recomputed instead of skipping, a throughput failure even if the values happened to match).
- Resource-contention guard (Risk 5): refuses to start if `ps aux | grep ic_engine` shows a live run.
- Production-data-corruption guard (Rule 2 addition, not in the plan's own threat register): cross-sectional `POOLED` cell membership is scoped only to the harness's own `--symbols` list, not the full corpus universe -- running `--refresh` against a `--training-window-end` that already has real full-corpus data would silently narrow/overwrite those POOLED cells. The harness refuses unless `--force`, and only auto-cleans up test rows it verified (via pre-flight) it owns 100% of -- leaves everything in place on a FAIL for inspection.
- Optional `--drift-study` mode: runs `ic_engine.py --refresh` at a baseline `training_window_end` and at `T+{lag}` for each requested lag, reporting mean/max absolute IC drift per lag -- diagnostic-only output informing whether `alpha.ic.refresh_min_new_fraction` should ever move off its migration-252 disabled seed. Same pre-flight/cleanup safety pattern applied to every window it touches.
- Migration 252 seeds `alpha.ic.refresh_min_new_fraction=0` (disabled); bound in `ICEngineConfig.from_apr()` as a forward-looking, currently-unwired field; classified COMPUTATIONAL in the fingerprint field partition (conservative margin, mirrors `sign_symmetric`'s precedent from 162-03).
- `_evaluate_staleness`'s docstring extended to explicitly pin the alert-only contract: wall-clock staleness never triggers auto-recompute; a fingerprint-valid cell is never auto-stale; data-driven refresh is only ever an explicit `--training-window-end` bump or `--refresh` override.
- **Live-verified the empirical proof this whole 162 arc exists to produce:** ran the harness for real against production data (dedicated throwaway `training_window_end=2020-01-02`, symbols `SPY QQQ IWM TLT GLD`, `tf=1d`). Run A (forced fresh) took 93.9s and wrote 5890 rows; run B (fingerprint-skip) took 3.0s and touched zero rows (`n_symbols_skip=5, n_symbols_compute=0, n_cs_skip=15, n_cs_compute=0` in `ic_engine.log`) -- yet produced an identical 5890-row snapshot, `computed_at` included. **PASS: the fingerprint captures everything that determines a cell's IC.** Test rows auto-cleaned up after the PASS; the real production corpus (902,969 rows at `training_window_end=2025-12-24`) confirmed untouched throughout. Also live-verified the optional `--drift-study` path (2 lags, mean abs IC drift 0.0016 at lag 1, 0.0034 at lag 5 -- small and monotonic, as expected; cleaned up after).

## Task Commits

Each task was committed atomically:

1. **Task 2 (Seed refresh_min_new_fraction + confirm staleness alert-only)** - `9f996029` (feat) -- committed first since it's simpler and self-contained; the plan's own task ordering doesn't require Task 1 to land before Task 2.
2. **Task 1 (Fresh-vs-fingerprint-skip equivalence harness)** - `4bd56991` (feat) -- includes the live-DB bug fix to `_compute_upstream_watermark` and the migration-249-through-252 live-DB application, both discovered/required while actually running the harness.

## Files Created/Modified

- `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py` - the equivalence harness + optional drift study (new)
- `production/migrations/252_ic_refresh_min_new_fraction.sql` - seeds `alpha.ic.refresh_min_new_fraction=0` (new)
- `services/ic_engine.py` - `ICEngineConfig.refresh_min_new_fraction` field + `from_apr()` binding + COMPUTATIONAL classification; `_evaluate_staleness` docstring extended; `_compute_upstream_watermark`'s `market_regimes` query fixed (`regime` -> `regime_label`)
- `tests/unit/test_ic_engine_fingerprint.py` - one docstring correction matching the column-name fix (test itself was DB-free and already passing; the bug was only reachable via a live query)

## Decisions Made

- **Task commit ordering:** committed Task 2 before Task 1 despite the plan listing Task 1 first -- Task 2 is simpler, fully self-contained, and has no dependency on Task 1's harness; committing it first kept each commit minimal and atomic rather than bundling the migration/config work into the same commit as the harness script.
- **Equivalence check's two-signal diff:** see key-decisions above.
- **Live-DB column list correction:** see key-decisions above.
- **Production-data-corruption guard:** see key-decisions above -- this is the single most consequential addition beyond the plan's literal text, closing a real gap the plan's own threat register didn't anticipate (T-162-04-01/02/03 cover resource contention, stale-serve, and premature-carry-forward, but not narrow-subset-refresh corrupting a shared corpus cell).
- **Chose a dedicated throwaway `training_window_end` (2020-01-02) rather than the real production window (2025-12-24)** for the live verification run -- this is exactly what the new production-data-corruption guard is designed to enforce, and demonstrates the intended safe operating pattern for future invocations of this harness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `_compute_upstream_watermark`'s wrong column name (`regime` vs `regime_label`)**
- **Found during:** Task 1's live-DB verification run (first real invocation of the cross-sectional watermark path since 162-03 wrote it -- 162-03's own SUMMARY explicitly noted this path was never exercised against a live DB in its worktree sandbox)
- **Issue:** `market_regimes` table's regime-label column is `regime_label`, not `regime` -- confirmed via `\d market_regimes`. The watermark query's `string_agg(regime, ...)` crashed with `UndefinedColumnError` on the very first cross-sectional fingerprint computation against real data. `main()`'s own `cs_regimes` discovery query (a few hundred lines away in the same file) already used the correct column name -- only this one watermark query had the typo.
- **Fix:** Changed `string_agg(regime, ...)` to `string_agg(regime_label, ...)`; updated the function's own comment and a matching test docstring for consistency.
- **Files modified:** `services/ic_engine.py`, `tests/unit/test_ic_engine_fingerprint.py`
- **Verification:** `.venv/bin/pytest tests/unit/test_ic_engine_fingerprint.py -q` (30/30 pass, DB-free), then re-ran the live harness end-to-end -- PASS.
- **Committed in:** `4bd56991`

**2. [Rule 2 - Missing Critical] Production-data-corruption pre-flight guard added to both the equivalence check and the drift study**
- **Found during:** Task 1 design, before any live run -- reasoning through how `--refresh`'s cross-sectional recompute scope actually works (traced live in `main()`: `symbols_by_group` is built strictly from the CLI `--symbols` list, not a DB-wide group-membership query)
- **Issue:** The plan's threat register (T-162-04-01/02/03) covers resource contention, stale-serve divergence, and premature carry-forward, but not this: running the harness's `--refresh` against a `--training-window-end` that already has real full-corpus POOLED data would DELETE-then-recompute those cells using only the harness's narrow symbol subset, silently corrupting the shared corpus.
- **Fix:** `_preflight_check_no_existing_rows` refuses to proceed (exit nonzero) if any `feature_ic_scores` rows already exist for the requested (symbols + POOLED, tfs, training_window_end) combination, unless `--force`. Only rows confirmed empty pre-flight are auto-cleaned up on success. Applied to both the equivalence check and the (initially-missing) drift-study path, caught and fixed before the drift-study's own live test run.
- **Files modified:** `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py`
- **Verification:** Live-verified directly -- the harness's real run used a dedicated throwaway window and left the actual production corpus (902,969 rows at the real `training_window_end`) completely untouched, confirmed by direct query before and after.
- **Committed in:** `4bd56991`

**3. [Rule 3 - Blocking] Applied migrations 249-252 to the live production database**
- **Found during:** Task 1's first live-DB run attempt (`relation "ic_cell_fingerprints" does not exist`)
- **Issue:** Phase 162's migrations (249/250/251/252) had only ever been authored and unit-tested inside worktree sandboxes with no live database connection (162-01/02/03's SUMMARYs all explicitly flag this limitation) -- none had actually been applied to the live production DB. This plan's live-DB verification requirement is the first point in the whole phase where that gap became blocking.
- **Fix:** Applied all 4 migrations via `psql -f` in order (249, 250, 251, 252) -- all are idempotent `IF NOT EXISTS`/`ON CONFLICT DO NOTHING` patterns, safe to apply directly; confirmed each succeeded and the resulting schema/config matches expectations before proceeding.
- **Files modified:** none (database schema/config only, not tracked files)
- **Verification:** `SELECT to_regclass('ic_cell_fingerprints')` and `SELECT config_value FROM config_state WHERE config_key='alpha.ic.refresh_min_new_fraction'` both confirmed live post-application.
- **Committed in:** not a tracked change (database-only)

---

**Total deviations:** 3 (1 bug fix, 1 missing-critical safety addition, 1 blocking/environment)
**Impact on plan:** All three are direct, necessary consequences of this being the phase's first live-DB execution point. #1 is a real bug that would have crashed every future cross-sectional fingerprint computation in production -- caught only because this plan's own objective (empirical live-DB proof) forced an actual live run. #2 closes a genuine corruption risk the plan's threat register didn't anticipate. #3 is required environment setup, not scope creep -- no prior plan in this phase had DB access to apply its own migrations.

## Issues Encountered

**Worktree base was stale at spawn time** -- same recurring pattern as 162-02/162-03's sessions: this worktree's branch had diverged from the expected base commit (`cb7b63446dc92ccbed9d5f3c0c6a81f4f41762b7`, the post-162-03-merge commit this plan depends on). Per the mandatory `worktree_branch_check` step, ran `git reset --hard cb7b63446dc92ccbed9d5f3c0c6a81f4f41762b7` to align (sanctioned, not a self-recovery on a protected branch -- HEAD was and remained on `worktree-agent-a096e515abd9cb574` throughout).

**No `.venv` in this worktree** (documented project gotcha, same as every prior 162 plan): symlinked `<worktree>/.venv -> /home/bg/dev/indicagent/.venv` to resolve the pre-commit hook's ruff/black tool discovery. Filesystem-only, not a tracked change.

**Live schema drift beyond migration 156's original DDL** -- `feature_ic_scores` in production has 15 additional columns (`ic_shrunk`, `regime_scope`, `partial_ic`, `sign_hit_rate`, `cumulative_e_value`, etc.) added by later phases, and 3 columns from migration 156 (`is_decaying`, `decay_detected_at`, `recovery_eligible_at`) no longer exist. The harness's column lists were built directly from a live `\d feature_ic_scores` query rather than migration 156's text, per the orchestrator's explicit warning not to trust original pre-refactor references.

**A leftover git-tracked side effect (`.planning/corpus_manifests/ic_engine.json`) got overwritten by the live test invocations** (`CorpusManifest` writes run metadata there on every `ic_engine.py` invocation, including test runs). Caught before committing via `git status --short`; reverted with a targeted `git checkout -- .planning/corpus_manifests/ic_engine.json` (sanctioned single-file discard, not a blanket reset) so the real production run's manifest state wasn't lost.

## User Setup Required

None - no external service configuration required. (Database migrations 249-252 were applied as part of this plan's own execution, documented above -- not a manual step left for the user.)

## Next Phase Readiness

- **Phase 162 is now fully executed** (4/4 plans: 162-01 structural extraction/memory-bounding, 162-02 per-tf bootstrap threads, 162-03 whole-cell fingerprint gate, 162-04 this plan's live-DB equivalence proof). SC-1 (no-op re-run throughput) has a real measured data point from this plan's live run (93.9s forced-fresh vs. 3.0s skip on a 5-symbol/1-tf subset -- ~31x faster on the skip path; full-corpus wall-clock timing at all 4 tfs is still an ops-level measurement for whoever runs the next real corpus pass, not re-derived here). SC-4 (skip-path output identity including `bh_adjusted_p`/`passes_fdr`) is now empirically PASS, not just unit-tested.
- Migrations 249-252 are now live in production -- any future `ic_engine.py` invocation (real corpus run or otherwise) will use the whole-cell fingerprint gate, the per-tf bootstrap thread config, and the feature-blocked memory-bounding from this whole phase.
- No blockers. Full `tests/unit/` suite green throughout (only the same 3 pre-existing, unrelated skips carried from 162-01/02/03's baseline).
- **`alpha.ic.refresh_min_new_fraction` stays at its migration-252 seed (0/disabled)** -- the `--drift-study` mode exists and was live-verified functional, but a full stratified drift study (many cells, longer lag range) informing whether to move off 0 was not run as part of this plan (matches the plan's own framing: "the study OUTPUT is what would later justify a nonzero seed," an ops-level follow-up, not this plan's gate).

---
*Phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t*
*Plan: 04*
*Completed: 2026-07-23*

## Self-Check: PASSED

Both created files confirmed present on disk (`test -f`). Both task commit
hashes (`9f996029`, `4bd56991`) confirmed present in `git log`. No missing
items.
