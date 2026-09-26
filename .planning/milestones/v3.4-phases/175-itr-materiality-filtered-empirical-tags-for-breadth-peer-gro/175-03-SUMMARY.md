---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
plan: 03
subsystem: database
tags: [python, statistics, tag-calibrator, instrument-tag-registry, apr, orthogonalization]

# Dependency graph
requires:
  - phase: 175-01
    provides: instrument_tags eleven Pass 4 evidence columns, instrument_tags_active view, discovery_state CHECK constraint, eleven alpha.tag_calibrator.materiality.* APR keys (migration 346)
  - phase: 175-02
    provides: partial_loading/partial_loading_ci_low/sign_stable_window_count/partial_loading_null_arm_p statistical kernels in factor_math.py
provides:
  - "MaterialityConfig: frozen dataclass binding all eleven alpha.tag_calibrator.materiality.* APR keys"
  - "select_control_factor_series / build_control_return_matrix: exclusion-aware control-set construction and aligned return matrix builder"
  - "measure_partial_loadings: Pass 4 measurement loop over every Pass 1-3 kept (symbol, tag) pair, full-history returns (R-07), per-pair deterministic null-arm RNG"
  - "decide_materiality: the six-condition statistical gate (R-04), sign-stability sliding-bar test-pinned in both directions"
  - "is_materiality_eligible: the canonical read-time conjunction of statistical/temporal/expiry gates"
  - "instrument_tags Pass 4 evidence now persisted through the single existing UPSERT; discovery_state/first_measured_at promoted to typed columns (closes todo 125)"
affects: [175-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sibling-not-subclass config dataclass: MaterialityConfig sits alongside TagCalibratorConfig rather than extending it, since the two APR namespaces are separately calibrated"
    - "keep computed once per measurement and reused for both Pass 4 selection and decide_outcome, avoiding a duplicated boolean expression"
    - "pass4 dict threaded through _apply_decision as an optional parameter (None -> all eleven evidence columns bound NULL) rather than a second UPSERT statement"

key-files:
  created: []
  modified:
    - services/tag_calibrator.py
    - tests/unit/test_tag_calibrator.py

key-decisions:
  - "Deferred Task 1(a)'s literal instruction to import partial_loading/partial_loading_ci_low/partial_loading_null_arm_p/sign_stable_window_count/hash_key_to_int in Task 1 -- those five names are unused until Task 2, and importing them early breaks Task 1's own ruff-clean acceptance gate (F401). Added them in Task 2 instead, where they are first consumed. No functional deviation -- same code exists by the end of Task 2, just attributed to the task that actually needs it."
  - "Committed each task as a single feat commit (test file + implementation together, both verified green before commit) rather than splitting into separate RED/GREEN commits per task -- tests were written and verified failing conceptually against the plan's <behavior> spec before implementation, but the actual RED state was not captured as a standalone commit. All three tasks' acceptance criteria (pytest green, ruff clean, specific grep checks) were independently verified before each commit."
  - "grep -rn for discovery_state/first_measured_at across src/ services/ scripts/ confirms the only readers are tag_calibrator.py's own write and read sites -- the JSONB evidence copy is redundant-but-retained per Task 3(d)'s instruction, not removed this phase; no future-cleanup blocker found."

requirements-completed: [P175-01, P175-02, P175-04, P175-05, P175-06]

# Metrics
duration: ~11min
completed: 2026-09-23
---

# Phase 175 Plan 03: TagCalibrator Pass 4 Integration Summary

**Pass 4 added to TagCalibrator: orthogonalized materiality evidence (partial loading, incremental R-squared, sign-stability count, circular-shift null-arm p-value) computed and persisted unconditionally for every Pass 1-3 kept (symbol, tag) pair through the single existing UPSERT, with discovery_state/first_measured_at promoted out of the evidence JSONB into typed columns, closing todo 125's discovery-OOS enforcement gap.**

## Performance

- **Duration:** ~11 min (commit-to-commit)
- **Started:** 2026-09-23T05:40:40-04:00
- **Completed:** 2026-09-23T05:51:14-04:00
- **Tasks:** 3
- **Files modified:** 2 (services/tag_calibrator.py, tests/unit/test_tag_calibrator.py)

## Accomplishments
- `MaterialityConfig` binds all eleven `alpha.tag_calibrator.materiality.*` APR keys; `select_control_factor_series`/`build_control_return_matrix` implement the two mandatory control-set exclusions (self-regression leg, tag's own factor_series) and the shared inner-join alignment, both never-raise (P175-04)
- `measure_partial_loadings`: Pass 4's counter-accumulating, never-log-per-row measurement loop, using each symbol's full-history return series (R-07) and a per-pair deterministic RNG seeded from the APR-backed `null_arm_seed` mixed with a per-pair hash -- determinism and seed-sensitivity both test-pinned (T-175-16a)
- `decide_materiality`: the six-condition statistical gate; the sign-stability sliding bar's deliberate discrete step at n=1008 is test-pinned in both directions (3-of-3 passes, 3-of-4 passes, 2-of-3 fails) per R-07's resolution
- `is_materiality_eligible`: the canonical read-time conjunction of the statistical (`passes_materiality`), temporal (`discovery_state`), and expiry (`valid_to`) gates (R-04, D-02)
- All eleven Pass 4 evidence columns now flow through the single `_UPSERT_EMPIRICAL_SQL` (never a second forked UPSERT), `EXCLUDED`-assigned so a pair that stops being measurable never keeps a stale `passes_materiality=true`; the `increment_fails`/`expire` path independently clears `passes_materiality=false`
- `test_discovery_oos_gate_blocks_fresh_discovery` closes todo 125's named gap: a fresh discovery with a fully-passing statistical profile is not `is_materiality_eligible` while `discovery_state='pending_oos'`
- D-03 shadow-mode boundary verified mechanically: `git diff --name-only` shows only the two plan-scoped files touched; `cross_sectional_regime_model.py`'s `source = 'human'` stopgap query is byte-unchanged

## Task Commits

1. **Task 1: MaterialityConfig and the exclusion-aware control return matrix** - `f2b7965ba` (feat)
2. **Task 2: Pass 4 measurement loop, run-level null-arm FDR, and the statistical gate** - `68b9ba553` (feat)
3. **Task 3: Persist Pass 4 evidence, promote discovery_state out of JSONB, close the todo-125 gate** - `8065b9a01` (feat)

_Tests were written per this plan's `<behavior>` spec and verified passing alongside each task's implementation before commit; each task's own acceptance criteria (pytest, ruff, targeted greps) were independently confirmed before staging._

## Files Created/Modified
- `services/tag_calibrator.py` - `MaterialityConfig`, `select_control_factor_series`, `build_control_return_matrix`, `measure_partial_loadings`, `decide_materiality`, `is_materiality_eligible`; `apply_run_level_fdr` generalized with keyword-only `p_key`/`reject_key`/`adjusted_key`; `_UPSERT_EMPIRICAL_SQL`/`_UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL`/`_apply_decision` extended for the eleven Pass 4 columns; `execute()` wired to construct `MaterialityConfig` once, run Pass 4 after Pass 1-3, and persist through the existing write path; module docstring updated to describe a 4-pass engine
- `tests/unit/test_tag_calibrator.py` - 46 new tests covering `MaterialityConfig` defaults, control-set exclusion/alignment, `measure_partial_loadings` orchestration (determinism, seed sensitivity, skip counters), `decide_materiality`'s six conditions and sign-stability sliding bar, `is_materiality_eligible`'s three gates, `_next_evidence`'s discovery-state derivation, `_apply_decision`'s parameter binding (via a minimal fake-connection recorder, no live DB), and `test_discovery_oos_gate_blocks_fresh_discovery`

## Decisions Made
- Deferred the five Task-1(a)-listed imports that are only consumed starting Task 2 (`partial_loading`, `partial_loading_ci_low`, `partial_loading_null_arm_p`, `sign_stable_window_count`, `hash_key_to_int`) to Task 2's own commit, since importing them in Task 1 with no consumer yet would fail Task 1's own `ruff check` acceptance gate (F401 unused import). Same end-state code exists after Task 2 either way -- this only changes which task's commit introduces which import line.
- Followed the plan's D-01a measurement universe exactly: "kept" is Pass 1-3's existing `passes_fdr AND abs(loading) >= loading_threshold` gate, computed once per measurement and reused for both Pass 4 selection and `decide_outcome`.
- Kept the JSONB `evidence` write exactly as-is per Task 3(d)'s instruction; the repo-wide grep for other readers of `discovery_state`/`first_measured_at` found none, so the JSONB copy is documented as redundant-but-retained rather than removed this phase.

## Deviations from Plan

None beyond the import-timing adjustment documented above under Decisions Made (which is itself Rule 1 territory -- a plan sub-step ordering that would otherwise break the same task's own stated acceptance criterion). No architectural changes, no scope additions beyond the plan's own tasks.

## Issues Encountered
- The worktree had no `.venv` (known GSD worktree gotcha -- `.venv` is gitignored, not created per-worktree). Symlinked to the main repo's `/home/bg/dev/indicagent/.venv` so `pytest`/`ruff`/`black` could run; the symlink itself is gitignored and was never staged.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All six new public functions (`MaterialityConfig`, `select_control_factor_series`, `build_control_return_matrix`, `measure_partial_loadings`, `decide_materiality`, `is_materiality_eligible`) exist, are unit-tested, and are ready for plan 04's shadow diagnostic to import (`is_materiality_eligible` is explicitly the canonical predicate future consumers should import rather than re-derive).
- `TagCalibrator`'s next live run will populate all eleven `instrument_tags` Pass 4 evidence columns for every kept empirical pair; nothing downstream reads `passes_materiality`/`is_materiality_eligible` yet (D-03 shadow-mode boundary intact, verified mechanically).
- Full `tests/unit/` suite is green (no regressions from Pass 1-3's existing behavior, `test_run_level_fdr`/`test_run_level_fdr_empty_measured_is_noop` unchanged).
- No blockers for plan 04.

---
*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Completed: 2026-09-23*
