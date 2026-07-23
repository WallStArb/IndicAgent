---
phase: 166-frame-execution-recalibration
plan: 01
subsystem: database
tags: [apr, timescaledb, alpha-frames, ensemble-ic, calibration, postgres]

# Dependency graph
requires:
  - phase: 142B
    provides: alpha_frames hypertable, AlphaFrameWriter, CounterfactualTracker, counterfactual_mfe/mae
  - phase: 148
    provides: Gate 2 (execution proof) FAIL verdict — the direct trigger for this phase
provides:
  - alpha.frame.stop_atr_mult.<regime>.<tf> / alpha.frame.target_r_multiple.<regime>.<tf> APR namespace (72 keys)
  - alpha.ensemble_ic.stop_mae_percentile / target_mfe_percentile / stop_target_min_qualifying_symbols APR keys
  - alpha.frame.* structural-confluence threshold APR keys (7 keys) for the structural candidate Part 1
  - alpha.frame.geometry_source selector APR key (default global, backward-compatible)
  - diagnose166_frame_calibration.py — read-only empirical diagnosis of the stop/target calibration gap
  - Phase 163 liveness status recorded (NULL_PENDING_163) for Plan 166-06's structural-arm gate
affects: [166-02, 166-03, 166-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-(regime,tf) APR seed via DO-block FOREACH loop (migration 190/195 shape)"
    - "Uncensored-subpopulation percentile calibration (closed_target for stop, closed_max_hold for target) as the stop/target analog of EIC-02's decay-walk"

key-files:
  created:
    - production/migrations/253_alpha_frame_stop_target_calibration.sql
    - scripts/analysis/diagnose166_frame_calibration.py
    - tests/unit/test_diagnose166_frame_calibration.py
  modified: []

key-decisions:
  - "Diagnosis's stop/target selection criterion is percentile-of-rescaled-MAE/MFE (Finding 1), NOT a literal IC-decay-threshold-walk copy — stop/target are distance/reward-ratio parameters with no time-horizon analog"
  - "Migration 253 seeds fresh alpha.frame.* namespace only; zero reuse of archived feature.trade_framer.*/feature.zone_engine.*/weights.zone_engine.* key families (Finding 5)"
  - "Phase 163 execution stays a runtime-checked external prerequisite (NULL_PENDING_163 recorded, not force-executed inside this plan) — gates only Plan 166-06's structural arm"

patterns-established:
  - "Pattern: uncensored-subpopulation percentile calibration for distance/ratio parameters (stop_atr_mult via closed_target MAE, target_r_multiple via closed_max_hold MFE) — the stop/target sibling of EIC-02's decay-walk pattern for hold_max_bars"

requirements-completed: [D-01a, D-02, D-06]

# Metrics
duration: ~30min
completed: 2026-07-23
---

# Phase 166 Plan 01: Migration Foundation + Read-Only Frame Diagnosis Summary

**Seeded the alpha.frame.*/alpha.ensemble_ic.* APR namespace both Phase 166 candidates need (migration 253, 79 keys), shipped a read-only diagnosis proving current global stop_atr_mult=1.5/target_r_multiple=2.0 scalars are systematically too wide against every measured (regime,tf) cell's empirical uncensored excursion percentile, and confirmed Phase 163's structural-candidate prerequisite is NOT yet live (NULL_PENDING_163).**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-07-23T12:00:26Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 (2 created + 1 test file)

## Accomplishments

- **Task 0 (D-06 gate):** Confirmed Phase 163's `sr_support_dist`/`sr_resist_dist` columns are 100% NULL corpus-wide — `NULL_PENDING_163`, recorded as a valid, non-blocking phase outcome per the plan's own truths. This gates only Plan 166-06's structural arm; the baseline + scalar arms and diagnosis proceed unaffected.
- **Task 1:** Migration 253 applied live — 72 per-(regime,tf) scalar-candidate keys (36 `stop_atr_mult` + 36 `target_r_multiple`), 3 `alpha.ensemble_ic.*` calibration-selection params, 7 structural-confluence threshold keys, and `alpha.frame.geometry_source` (default `global`, backward-compatible). Zero reuse of archived `feature.trade_framer.*`/`feature.zone_engine.*`/`weights.zone_engine.*` namespaces (grep-verified).
- **Task 2 (D-01a):** Shipped `diagnose166_frame_calibration.py` — a read-only script comparing the current global stop/target scalars against empirical uncensored MAE/MFE excursion percentiles per (regime,tf), sourced from `alpha_frames.counterfactual_mae/mfe` rescaled to ATR-units via each row's own snapshotted `stop_atr_mult`. Live run against the champion `weight_epoch` (`143.1-08-champion`, in-sample only) shows the empirical stop AND target percentiles are narrower than the current global 1.5/2.0 scalars in every one of the 7 measured (regime,tf) cells — a real, informative confirmation of D-02's diagnosis that these scalars were never conditioned on regime/tf.

## Task Commits

Each task was committed atomically:

1. **Task 0: Verify Phase 163 prerequisite (D-06 Wave 0 gate)** — no file changes (verification only); result documented below and in this SUMMARY
2. **Task 1: Migration 253 — seed alpha.frame.* APR keys for both candidates** - `78a09117` (feat)
3. **Task 2: Diagnosis script — current calibration vs IC decay curve vs MAE/MFE (D-01a)** - `6da44823` (test)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode — orchestrator handles final merge)

## Files Created/Modified

- `production/migrations/253_alpha_frame_stop_target_calibration.sql` - 79 APR keys: 72 per-(regime,tf) scalar-candidate keys, 3 calibration-selection params, 7 structural-confluence thresholds, 1 geometry-source selector. Applied live and verified.
- `scripts/analysis/diagnose166_frame_calibration.py` - Read-only diagnosis: `_summarize_excursions` (per-(regime,tf) MAE/MFE percentile summary from uncensored subpopulations) + `_compare_to_current` (delta vs current global scalars). Zero writes (SELECT-only).
- `tests/unit/test_diagnose166_frame_calibration.py` - 4 unit tests covering ATR-rescaling correctness, closed_stop exclusion (088 censoring), and the comparison delta logic (including a None-handling edge case beyond the plan's minimum 3 tests).

## Decisions Made

- **Selection criterion (RESEARCH.md Finding 1):** stop placement = `stop_mae_percentile`-th percentile of `abs(counterfactual_mae) * stop_atr_mult` among `closed_target` frames only (uncensored — these frames never touched the stop); target placement = `target_mfe_percentile`-th percentile of `counterfactual_mfe` (R-units, unrescaled) among `closed_max_hold` frames only (uncensored — these frames never touched stop or target). `closed_stop` frames are right-censored at the stop threshold and excluded from the stop distribution (088 alignment); `closed_ic_decay` frames are excluded from both.
- **Migration 253's zone_buffer_atr (0.1) and min_width_atr (0.05) values** deliberately diverge from the archived confluence-scoring module's own constants (0.15/1.5 respectively) per the plan's explicit literal instructions — documented in each key's description as intentionally narrower, consistent with this candidate's smaller (VP+S-R only, not the full ~14-source spec table) candidate universe. `cluster_radius_atr` (0.5), `single_level_radius_atr` (0.25), `strength_weight` (0.6), and `proximity_weight` (0.4) are exact carry-overs from the archived module's live constants.
- **Diagnosis restricts to the champion `weight_epoch`** (`'143.1-08-champion'`, matching `score03_gate2_execution_eval.py`'s constant) rather than pooling across challenger frames — Gate 2 scored this population; the diagnosis of why it failed should measure against the same population.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked the worktree's missing `.venv` to the main repo's**
- **Found during:** Task 2 commit (pre-commit hook)
- **Issue:** This git worktree has no `.venv` (gitignored, not copied on worktree creation — a known GSD worktree gotcha). The pre-commit hook's ruff/black checks resolved `${REPO_ROOT}/.venv/bin/{ruff,black}` against the worktree root and found nothing, then fell back to `which ruff`/`which black` on PATH and also found nothing, blocking the commit entirely (not a real lint failure).
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a2cde65e71b2af809/.venv` — a symlink to the already-installed main-repo venv, not a new package install (no package-manager command invoked, so the Rule 3 install-exclusion does not apply). `.venv` stays gitignored; the symlink itself was confirmed absent from `git status --short` before and after.
- **Files modified:** none tracked (symlink only, outside git)
- **Verification:** `git status --short` before/after the symlink shows zero new tracked entries; pre-commit hook's ruff/black steps passed on retry
- **Committed in:** N/A (not a tracked file; enabled `6da44823`)

**2. [Documented finding, not a code fix] Task 0's live schema check found only 4 of the 10 listed Phase-163 columns currently present**
- **Found during:** Task 0
- **Issue:** The plan's action text listed 10 Phase-163 columns to verify present-in-schema (`poc_dist_atr`, `poc_rolling_dist_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `resistance_strength`, `support_strength`, `resistance_age_bars`, `support_age_bars`, `sr_level_count`, `sr_support_dist`). Direct `\d feature_vectors` inspection found only 4 structural-adjacent columns exist today: `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist` — all NULL. The other 8 listed columns (`poc_rolling_dist_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `resistance_strength`, `support_strength`, `resistance_age_bars`, `support_age_bars`, `sr_level_count`) do not yet exist in the schema at all.
- **Why this is not a blocker:** This matches RESEARCH.md's own Finding 2 verbatim ("The only structural-level-adjacent columns anywhere in v3 today are poc_dist_atr/va_position/sr_support_dist/sr_resist_dist — all four currently NULL corpus-wide, pending Phase 163") — the 4 live columns are pre-existing v3.0 Feature Factory placeholders; the other 8 are added by Phase 163's OWN migration (not yet executed), not something migration 253 or this plan was ever responsible for. No code action was taken or needed here — Task 0 is verification-only per its own file spec.
- **Files modified:** none (Task 0 has no file changes)
- **Committed in:** N/A — documented here and in "Task 0 result" below

---

**Total deviations:** 1 auto-fixed (Rule 3, environment-only), 1 documented finding (no code action, no blocker)
**Impact on plan:** Zero scope creep. The symlink is a pure environment fix; the schema finding confirms (does not contradict) the plan's own RESEARCH.md basis and does not change Task 0's recorded outcome (`NULL_PENDING_163`) or acceptance.

## Task 0 Result: Phase 163 Prerequisite Status

```
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc \
  "SELECT CASE WHEN count(*)>0 THEN 'LIVE' ELSE 'NULL_PENDING_163' END \
   FROM feature_vectors WHERE sr_support_dist IS NOT NULL;"
=> NULL_PENDING_163
```

**Status: `NULL_PENDING_163`.** Phase 163 ("VP/SR Structural Primitives") has NOT executed. This is a **VALID, non-failing phase outcome** — it gates ONLY Plan 166-06's structural arm. The baseline + scalar arms, this plan's diagnosis, and the phase's eventual verdict doc all proceed regardless (RESEARCH.md Open Question 1 resolution: Phase 163 is a runtime-checked external cross-phase prerequisite, deliberately NOT force-executed inside Phase 166). **Plan 166-06's structural-candidate runtime is explicitly gated on `/gsd-execute-phase 163` completing first** and re-checking this same query returns `LIVE`.

Schema presence check (10 listed columns): 4 of 10 currently present (`poc_dist_atr`, `sr_support_dist`, `sr_resist_dist`, and `va_position` — a non-listed sibling also found live), all NULL. The remaining 8 (`poc_rolling_dist_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `resistance_strength`, `support_strength`, `resistance_age_bars`, `support_age_bars`, `sr_level_count`) will be added by Phase 163's own migration when it executes — see Deviations #2 above.

## Issues Encountered

None beyond the two items documented under Deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 166-02 (scalar candidate `_calibrate_stop_target()`) can proceed immediately: migration 253's per-(regime,tf) keys and `alpha.ensemble_ic.*` selection params are live, and this plan's diagnosis output (uncensored MAE/MFE percentiles per cell) is the empirical basis for that calibration function's selection logic.
- Plan 166-03 (structural candidate Part 1) is **blocked on Phase 163 execution** (`NULL_PENDING_163`) — `/gsd-execute-phase 163` must complete and the liveness query must return `LIVE` before that plan's runtime can produce a real (non-degenerate-ATR-fallback) structural candidate. The migration 253 threshold keys it needs (`alpha.frame.cluster_radius_atr` etc.) are already seeded and ready.
- Plan 166-06 (validation gate / verdict) inherits the explicit structural-arm gating documented here.
- No blockers for the diagnosis's own conclusions: live-verified that the current global stop/target scalars are measurably too wide against every evaluable (regime,tf) cell in-sample — a real, actionable signal for Plan 166-02's calibration.

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*
