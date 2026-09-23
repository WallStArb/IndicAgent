---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: 05
subsystem: alpha-measurement-governance
tags: [ensemble_trainer, ic_engine, regime_scope, eligibility, feature_ic_scores, corpus-pipeline]

# Dependency graph
requires:
  - phase: 176-01
    provides: "D-01a evidence gate SWEEP_VERDICT=CONFIRMED with 31 non-empty SWEEP_SURVIVORS, unblocking this plan's execution"
  - phase: 176-02
    provides: "migration 350 (earnings_season CHECK constraint widening on feature_ic_scores.regime_scope)"
provides:
  - "ensemble_trainer._eligibility_where() excludes regime_scope='earnings_season' at the single shared builder, all three call sites"
  - "176-SCOPE-CONSUMER-AUDIT.md: decision-driving determination + verdict for all 39 other feature_ic_scores consumers"
  - "13 decision-driving consumers patched with the same exclusion clause"
affects: [176-04, 176-06, 176-07, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "regime_scope exclusion clause pattern: AND regime_scope <> 'earnings_season', added immediately after existing identity/scope predicates rather than as a bolt-on suffix"
    - "DECISION-DRIVING: yes|no determination made and recorded before assigning ALLOW-LISTED/NEEDS-FILTER/SCOPE-AGNOSTIC verdict, per file"

key-files:
  created:
    - .planning/phases/176-earnings-season-calendar-primitive-todo-353/176-SCOPE-CONSUMER-AUDIT.md
  modified:
    - services/ensemble_trainer.py
    - tests/unit/test_ensemble_trainer.py
    - scripts/analysis/personal_cost_hurdle_by_tf.py
    - scripts/analysis/personal_edge_paper_screen.py
    - scripts/debug/analysis/debug_analyze_feature_ic.py
    - scripts/ops/alpha/ops_canary_integrity_assert.py
    - scripts/ops/alpha/ops_dependence_length_diagnostic.py
    - scripts/ops/alpha/ops_ic_null_calibration.py
    - scripts/ops/alpha/ops_ic_shrinkage.py
    - scripts/ops/alpha/ops_interaction_primitives_pilot.py
    - scripts/ops/alpha/ops_lookahead_horizon_response.py
    - scripts/ops/alpha/ops_vol_normalized_target_ab.py
    - scripts/ops/corpus/ops_cost_hurdle_calibration.py
    - scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
    - scripts/ops/corpus/ops_oos_holdout_eval.py
    - src/observability/corpus_manifest_verifier.py
    - tests/unit/scripts/test_ops_dependence_length_diagnostic.py
    - tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py
    - tests/unit/scripts/test_ops_lookahead_horizon_response.py
    - tests/unit/scripts/test_ops_vol_normalized_target_ab.py
    - tests/unit/src/observability/test_corpus_manifest_verifier.py

key-decisions:
  - "Vintage-lookup-only queries (SELECT MAX(training_window_end) FROM feature_ic_scores) in decision-driving files were patched defensively even though currently semantically inert (earnings_season shares the main ic_engine run's training_window_end, confirmed via 176-04-PLAN.md) -- the plan's SCOPE-AGNOSTIC verdict is structurally prohibited for DECISION-DRIVING:yes files, and the fix costs one clause."
  - "ops_ic_shrinkage.py's leave-one-out (group_name, regime, tf) shrinkage prior likely wouldn't cross-contaminate the three original scopes even unfiltered (earnings-season regime labels form their own peer groups), but was patched anyway: appearing in a HARD GATE's input population at all violates measurement-only status regardless of numerical inertness."
  - "ops_corpus_progress.py's NEEDS-FILTER row was left unpatched (documented only): it is a pure informational progress dashboard, not chained into any pipeline runner, writes nothing, gates nothing -- DECISION-DRIVING: no, which the plan explicitly permits leaving unpatched with the fix recorded."
  - "ops_oos_holdout_eval.py and statistical_factor_residual_stage3_ic_falsification.py both carry explicit 'not a promotion gate' / 'context only' disclaimers in their docstrings, but were resolved differently: the former's in-sample count is a DIRECT input to its own computed drop-verdict (patched), the latter's feature_ic_scores query is inert context alongside an independently, locally recomputed pass/fail bar (left SCOPE-AGNOSTIC)."

requirements-completed: [ES-06]

duration: 23min
completed: 2026-09-23
---

# Phase 176 Plan 05: Ensemble Eligibility Isolation + Scope Consumer Audit Summary

**One-clause `regime_scope <> 'earnings_season'` exclusion in `ensemble_trainer`'s single eligibility builder, plus a 39-file consumer audit that found and patched 13 more decision-driving `feature_ic_scores` readers with the same gap.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-09-23T07:28:36-04:00 (worktree base commit)
- **Completed:** 2026-09-23T07:51:04-04:00
- **Tasks:** 2
- **Files modified:** 22 (2 in Task 1, 20 in Task 2, including the new audit doc)

## Accomplishments

- `ensemble_trainer._eligibility_where()` now provably cannot admit `regime_scope='earnings_season'` cells into ensemble training strata -- the exclusion lives once in the shared builder, all three existing call sites route through it unchanged, and the Component-E byte-identical equivalence test was deliberately re-baselined with a docstring recording why.
- A structural NULL-safety precondition for using `<>` (not `IS DISTINCT FROM`) is now enforced by a static migration-file test, so a future migration relaxing `feature_ic_scores.regime_scope` to nullable fails loudly instead of silently narrowing eligibility.
- Every other `feature_ic_scores` consumer in `services/`, `scripts/`, `src/` (no `api/` directory exists in this repo) got an explicit `DECISION-DRIVING: yes|no` determination made *before* its verdict, written to `176-SCOPE-CONSUMER-AUDIT.md` -- 39 files total, with the full verbatim grep output preserved for independent verification.
- 13 decision-driving consumers that would have silently mixed `earnings_season` rows into a result assuming the three-value vocabulary were patched with the same one-clause exclusion, including two scripts chained into `ops_corpus_pipeline_run.sh` (`ops_canary_integrity_assert.py`, a HARD-halt integrity gate; `ops_ic_shrinkage.py`, the D-05 HARD GATE that can flip `alpha.ensemble.ic_input`) and the crash-loud `corpus_manifest_verifier.py` gate that runs before `alpha_events` consumption.

## Task Commits

1. **Task 1: Exclude earnings_season scope from ensemble eligibility** - `42592ca6a` (feat)
2. **Task 2: Audit every remaining feature_ic_scores consumer** - `7cd883767` (feat)

_No TDD RED/GREEN split -- the plan's `tdd="true"` on Task 1 was satisfied by writing the new/updated tests in the same commit as the implementation change, verified green before commit (test infrastructure and existing test suite already covered the byte-identical equivalence property this task modifies)._

## Files Created/Modified

- `services/ensemble_trainer.py` - `_eligibility_where()` base_where clause gains `AND regime_scope <> 'earnings_season'`, with a comment recording the Phase 176 rationale and NULL-safety precondition.
- `tests/unit/test_ensemble_trainer.py` - `_OLD_BASE_WHERE` re-baselined; new `TestEarningsSeasonScopeExclusion` class (3 tests: both `sign_symmetric` values carry the exclusion, full clause still ends `passes_fdr = true`, static migration-file re-assertion that `regime_scope` is still `NOT NULL`).
- `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-SCOPE-CONSUMER-AUDIT.md` - full audit: summary table (39 rows) + raw verbatim grep output for both `feature_ic_scores` and `regime_scope` greps + phase-level measurement-only contract statement.
- 13 patched consumer files (see frontmatter `key-files.modified`) - each gained `AND regime_scope <> 'earnings_season'` (or the vintage-lookup equivalent) at the exact line(s) recorded in the audit table.
- 5 existing test modules extended with a regression test asserting the new exclusion clause is present in the relevant SQL constant/source.

## Decisions Made

See `key-decisions` in frontmatter. In short: patch defensively wherever a file is decision-driving even if a specific query is currently semantically inert (vintage lookups), and resolve genuinely ambiguous decision-driving calls toward "yes" per the plan's explicit asymmetry mandate.

## Deviations from Plan

**1. [Rule 1 - Bug, self-caught during authoring] Fixed a duplicate `WHERE` clause introduced mid-edit in `ops_vol_normalized_target_ab.py`**
- **Found during:** Task 2, patching `_REGIMES_SQL`
- **Issue:** An `Edit` call inserted `WHERE regime_scope <> 'earnings_season' AND` directly after `FROM feature_ic_scores` without accounting for the pre-existing `WHERE symbol = $1 AND ...` clause on the next line, producing invalid SQL with two `WHERE` keywords.
- **Fix:** Re-read the file, corrected both `_REGIMES_SQL` and `_BASELINE_SQL` to append the exclusion as a trailing `AND` clause instead of a leading one.
- **Files modified:** `scripts/ops/alpha/ops_vol_normalized_target_ab.py`
- **Verification:** File re-read post-fix to confirm single well-formed `WHERE` clause; `.venv/bin/pytest tests/unit/scripts/test_ops_vol_normalized_target_ab.py -q` green; full `tests/unit/` suite green.
- **Committed in:** `7cd883767` (Task 2 commit; the bug never reached a committed state, caught before staging)

**2. [Rule 2 - Missing critical, plan-anticipated but self-discovered scope] Patched a broader set of decision-driving consumers than the plan's `<read_first>` list named**
- **Found during:** Task 2's grep sweep
- **Issue:** The plan's `<read_first>` section named 5 specific files to read as examples of the allow-listing/scope-handling patterns already in the codebase (`equity_regime_separation_gate.py`, `phase144_regime_separation_gate.py`, `ops_ic_fingerprint_equivalence.py`, `ops_ensemble_ic_diagnosis.py`, `statistical_factor_residual_stage3_ic_falsification.py`), but the actual union of both greps returned 39 files, of which 14 (13 patched + 1 documented-unpatched) needed a NEEDS-FILTER verdict the plan's read_first list didn't anticipate by name.
- **Fix:** This is exactly what Task 2's own action step mandates ("Patch, in this task, every NEEDS-FILTER file marked DECISION-DRIVING: yes -- do not defer it to a note"), so no deviation from the plan's instructions occurred -- documenting here only because the volume (13 files, ~25 individual query edits) was larger than the read_first list alone would suggest to a reader skimming just that section.
- **Files modified:** See frontmatter `key-files.modified`.
- **Verification:** Full `tests/unit/` suite green after all patches; ruff/black clean on every touched file.
- **Committed in:** `7cd883767`

---

**Total deviations:** 2 (1 self-caught bug during authoring, 1 scope clarification -- both fully resolved before commit, no net impact on plan intent).
**Impact on plan:** None outside normal execution. No scope creep beyond what Task 2's action step explicitly required.

## Issues Encountered

None beyond the duplicate-WHERE authoring bug documented above (caught and fixed before any commit).

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. All patched queries are real, executable SQL changes verified against the live schema's column names (`regime_scope`, confirmed `NOT NULL` via migration 187, widened to admit `'earnings_season'` via migration 350 from plan 176-02).

## Threat Flags

None. This plan's threat model (T-176-05-01 through T-176-05-05) is fully addressed by the implementation: no new network endpoints, auth paths, or schema changes were introduced -- only WHERE-clause exclusions on existing read paths and one already-planned eligibility-builder edit.

## Next Phase Readiness

- Plan 176-06 (cross-sectional earnings-season IC cells) can now execute knowing its output cannot reach ensemble weighting or alpha emission via `ensemble_trainer.py`, and that the broader consumer surface has been swept and patched.
- Plan 176-04 (per-symbol earnings-season IC cells + `ic_engine.py`'s own in-file lifecycle guard) is unaffected by this plan (touches a disjoint file) and can run in parallel per the plan's own wave note.
- No blockers identified for 176-07/176-08.

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*
