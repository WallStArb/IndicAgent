---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
plan: 02
subsystem: statistics
tags: [numpy, scipy, ic-math, orthogonalization, null-arm, tag-calibrator]

# Dependency graph
requires:
  - phase: 146-empirical-instrument-tag-calibrator
    provides: standardized_loading/loading_hac_pvalue Pearson-convention loading kernel in factor_math.py that this plan's partial_loading extends
provides:
  - "partial_loading(instrument_ret, factor_ret, controls, condition_max) -> (partial_loading, incremental_r2, n): Pearson-convention orthogonalized loading"
  - "partial_loading_ci_low(...) -> float: Fisher-z lower bound on abs(partial_loading), HAC-inflated"
  - "sign_stable_window_count(...) -> (n_sign_stable, n_evaluable): disjoint tail-anchored rolling-window sign stability"
  - "partial_loading_null_arm_p(...) -> float: D-06 circular-shift null-arm p-value, factor-proxy-only shift"
affects: [175-03-tag-calibrator-pass-4-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pearson-convention partial correlation via shared residualization helper mirroring ic_math.partial_spearman_ic's shape (center, check_condition_number gate, one shared lstsq call) but on raw returns, not ranks"
    - "Precomputed pseudo-inverse null-arm draw loop: one np.linalg.pinv plus n_draws matmuls instead of n_draws lstsq solves, to keep a Monte-Carlo null arm affordable inline in a per-pair corpus loop"

key-files:
  created: []
  modified:
    - src/intelligence/statistics/factor_math.py
    - tests/unit/test_factor_math.py

key-decisions:
  - "R-01: partial_loading uses the Pearson convention on raw centered returns, not ic_math.partial_spearman_ic's rank transform -- this project's existing loading/loading_threshold values (Phase 146) are Pearson-calibrated"
  - "R-06: incremental_r2 = R2_full - R2_controls (strictly <= partial_loading**2), not the squared partial correlation, matching D-05's instruction to seed the more conservative gate reading"
  - "R-05: partial_loading_ci_low's two-sided alpha reuses the existing alpha.tag_calibrator.fdr_alpha (0.05) APR key rather than introducing an 11th key for the same number"
  - "D-06: the null arm shifts only the factor_series proxy's own return series, never the candidate's return or a control column -- test-enforced via a monkeypatched _circular_shift_null recorder"

patterns-established:
  - "Shared _partial_residuals private helper keeps partial_loading and partial_loading_ci_low from duplicating the residualization/condition-number-gate logic"
  - "Module-wide np.linalg.lstsq call-site count pinned at exactly 2 (one shared residualization solve, one full-model R2 solve) as an acceptance criterion, enforced by grep"

requirements-completed: [P175-01, P175-05]

# Metrics
duration: 6min
completed: 2026-09-23
---

# Phase 175 Plan 02: Factor-Math Statistical Kernels Summary

**Four new pure-function statistical kernels in `factor_math.py` (Pearson partial loading + incremental R², Fisher-z lower-CI bound, disjoint tail-anchored sign-stability count, and a D-06-compliant circular-shift null arm), each reusing an existing `ic_math` primitive for its class of problem rather than reimplementing it.**

## Performance

- **Duration:** 6 min (commit-to-commit; RED/GREEN cycle across 3 tasks)
- **Started:** 2026-09-23T05:28:13-04:00
- **Completed:** 2026-09-23T05:33:38-04:00
- **Tasks:** 3 (each following RED test commit -> GREEN implementation commit)
- **Files modified:** 2

## Accomplishments
- `partial_loading`/`partial_loading_ci_low`: Pearson-convention orthogonalized loading and its HAC-inflated Fisher-z lower bound, sharing one `_partial_residuals` helper that mirrors `ic_math.partial_spearman_ic`'s shape without its rank transform (R-01)
- `sign_stable_window_count`: genuinely new code (no existing analog anywhere in the codebase per RESEARCH.md Pitfall 3) implementing disjoint, tail-anchored rolling-window sign-stability counting with short-windows-skipped-not-padded and NaN-windows-excluded-from-both-terms semantics, each pinned by a dedicated test
- `partial_loading_null_arm_p`: the D-06 circular-shift null arm, shifting only the factor proxy's own return series (test-enforced via a monkeypatched `_circular_shift_null` recorder), with the pseudo-inverse precomputed once outside the draw loop so the module's total `np.linalg.lstsq` call-site count stays at exactly 2
- All four functions exported via `__all__`; zero `rankdata`, zero `np.roll`, zero `statsmodels` imports anywhere in the module (acceptance-criterion-enforced)

## Task Commits

Each task followed TDD RED (failing test) -> GREEN (implementation) as two commits:

1. **Task 1: Pearson partial-loading kernel** - `c0abc6645` (test, RED) -> `0e182b358` (feat, GREEN)
2. **Task 2: Sign-stability window count** - `831c4ee75` (test, RED) -> `3c089a14b` (feat, GREEN)
3. **Task 3: D-06 circular-shift null arm** - `4c483138b` (test, RED) -> `bd7ab661a` (feat, GREEN)

_No refactor commits needed -- each GREEN commit passed lint/format checks without a follow-up cleanup pass._

## Files Created/Modified
- `src/intelligence/statistics/factor_math.py` - added `_partial_residuals` (private), `partial_loading`, `partial_loading_ci_low`, `sign_stable_window_count`, `partial_loading_null_arm_p`; added `scipy.stats.norm` and `ic_math._circular_shift_null` imports; extended `__all__`
- `tests/unit/test_factor_math.py` - added 22 new tests (13 for Task 1, 6 for Task 2, 7 for Task 3, plus the `test_partial_loading_known_value` name required by this plan's artifact contract) covering known-value recovery, every degenerate-input guard, window-boundary semantics, and the D-06 shift-target contract

## Decisions Made
All four resolutions (R-01, R-05, R-06, D-06) were pre-carried by the plan itself (from RESEARCH.md's Open Questions, already subjected to the D-07 cross-AI review gate before execution) -- none required a new decision during execution. Two small in-execution adjustments, both mechanical, not substantive:
- Reworded one docstring sentence in `_partial_residuals` that literally contained the substring `np.linalg.lstsq` inside prose, which the acceptance criterion's `grep -c 'np.linalg.lstsq'` count would have (correctly) flagged as a 3rd call site when it was only a comment. Rephrased to "one shared least-squares call" to keep the grep-based acceptance criterion meaningful.
- Replaced the banned glossary term for a two-sided alpha with "alpha" in one docstring sentence -- CLAUDE.md-adjacent `docs/foundation/glossary.md` bans that term (p-value framing is required); this is a pure terminology fix, no semantic change.

## Deviations from Plan

None - plan executed exactly as written. Both adjustments above are docstring wording only, made to satisfy the plan's own acceptance criteria and the project's glossary enforcement, not functional changes.

## Issues Encountered
- The worktree had no `.venv` (known GSD worktree gotcha -- `.venv` is gitignored and not created per-worktree). Symlinked `.venv` in the worktree to the main repo's `/home/bg/dev/indicagent/.venv` so the pre-commit hook's `ruff`/`black` checks and `pytest` could run; this symlink is itself gitignored and was never staged or committed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All four kernels this plan's plan 03 (`TagCalibrator` Pass 4 integration) needs are implemented, tested, and exported: `partial_loading`, `partial_loading_ci_low`, `sign_stable_window_count`, `partial_loading_null_arm_p`.
- Full `tests/unit/` suite is green (no regressions from the new imports/`__all__` additions).
- Plan 03's R-02 override (null arm runs inline inside `TagCalibrator.execute()`) depends on `partial_loading_null_arm_p`'s precomputed-pseudo-inverse cost profile -- verified here (module-wide lstsq count pinned at 2, no per-draw solve).

---
*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Completed: 2026-09-23*
