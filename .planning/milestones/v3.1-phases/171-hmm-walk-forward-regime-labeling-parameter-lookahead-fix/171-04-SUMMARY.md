---
phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix
plan: 04
subsystem: regime-measurement
tags: [hmm, gaussianhmm, walk-forward, regime-labeling, bootstrap-ic, config_state, diagnostic-script]

# Dependency graph
requires:
  - phase: 171 (plans 01-03, prior waves)
    provides: _walk_forward_hmm_labels / _hmm_seed_stability_check / _seed_prior_from_label
      TDD-tested and landed in services/regime_writer.py (todo 248), not yet wired into
      the live path
provides:
  - Real-data call site for _hmm_seed_stability_check (REQ-5), closing its
    invoked-nowhere status
  - hmm_walk_forward_seed_stability_pilot.py: multi-cell (8 symbols x 4 tfs) seed-stability
    diagnostic sampling walk-forward training-prefix boundaries, corpus-wide MINIMUM
    agreement headline, cache/hmm_seed_stability_pilot_results.json for plan 171-06's
    quarantine decision
  - hmm_n_restarts_walk_forward_comparison_pilot.py: D-03's two-block attribution
    comparison (walk-forward-vs-production, n_restarts=1-vs-N), entirely in-memory,
    cache/hmm_n_restarts_comparison_results.json for plan 171-05's evidence
affects: [171-05, 171-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read-only analysis scripts read HMM/walk-forward hyperparameters from config_state
      via a plain SELECT at startup (no live ConfigService instance), with module-level
      dict fallbacks matching the interfaces block, so the pilot never silently diverges
      from what production actually runs."
    - "Numerical-instability catch pattern for thin-prefix full-covariance GaussianHMM
      fits: catch (np.linalg.LinAlgError, ValueError) per fit attempt, record as a hard
      stability failure (0.0 agreement / cell abort with printed reason) rather than
      crashing the whole multi-cell diagnostic run. The underlying regime_writer.py
      functions are never modified to work around this -- the catch lives entirely in
      the calling analysis script."
    - "D-03 parallel-arm attribution: two independent bootstrap-CI verdict blocks per
      cell, never one conflated number, so a walk-forward effect and a multi-restart
      effect stay separately attributable."

key-files:
  created:
    - scripts/analysis/hmm_walk_forward_seed_stability_pilot.py
    - scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py
  modified: []

key-decisions:
  - "Seed-stability pilot catches GaussianHMM covariance-singularity LinAlgError per
    walk-forward boundary and records it as min_pairwise_agreement=0.0 (a hard FAIL),
    rather than letting the whole multi-cell run crash on one bad boundary -- a fit
    crash IS evidence of instability, not a script bug to hide."
  - "n_restarts comparison pilot implements the multi-restart walk-forward arm entirely
    inline (_walk_forward_hmm_labels_multi_restart), replicating _compute_symbol_tf's
    existing multi-seed restart + corrected convergence-retry selection loop (todo
    108/229) -- services/regime_writer.py is not modified, matching D-03's explicit
    'evaluate empirically before threading a new parameter through production' scope."
  - "tf-major cell ordering (1d symbols first, then 1h, 15m, 5m) so a full run surfaces
    the cheapest cells' results before the expensive ~390k-row 5m walk-forward prefixes."

requirements-completed: [REQ-5]

# Metrics
duration: 7min
completed: 2026-08-08
---

# Phase 171 Plan 04: HMM Walk-Forward Diagnostic Scripts (Seed Stability + n_restarts Comparison) Summary

**Two read-only diagnostic scripts: a real-corpus seed-stability check closing REQ-5's invoked-nowhere gap (min-not-average corpus-wide gate at 0.25), and an in-memory two-block n_restarts attribution comparison that keeps D-03's walk-forward-vs-multi-restart effects independently measurable without touching `feature_vectors` or `regime_writer.py`.**

## Performance

- **Duration:** ~7 min (commit-to-commit; investigation/design time not included in this figure)
- **Started:** 2026-08-08T06:25:08Z (Task 1 commit)
- **Completed:** 2026-08-08T06:30:18Z (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 2 (both new)

## Accomplishments
- `_hmm_seed_stability_check` (`services/regime_writer.py`) now has a real call site
  against real corpus OHLCV, run at the actual walk-forward training-prefix boundaries
  `_walk_forward_hmm_labels` fits, across 8 symbols x 4 timeframes.
- Discovered and handled a genuine numerical-instability pathology in real data: a
  full-covariance GaussianHMM fit on a thin (~504-obs) training prefix can raise a
  non-positive-definite covariance `LinAlgError` mid-EM (confirmed live on TLT/1d and
  SPY/1d). Both scripts catch this and record it as a hard stability failure rather than
  crashing the diagnostic run.
- D-03's two-arm comparison (walk-forward-vs-production, n_restarts=1-vs-N) is fully
  measurable in memory with two independently-attributable bootstrap-CI verdict blocks,
  verified end-to-end on GLD/1d: PRODUCTION vs WALK-FORWARD point_ic printed separately,
  n_restarts=1 vs n_restarts=2 printed separately, D-03 ATTRIBUTION line computed from a
  strict-majority gate across evaluated cells.
- `services/regime_writer.py` is byte-for-byte unmodified by this plan (`git diff --stat`
  empty), confirming the multi-restart arm and the numerical-failure handling stayed
  fully scoped to the two new analysis scripts.

## Task Commits

Each task was committed atomically:

1. **Task 1: Real-data seed-stability pilot script (REQ-5)** - `4dc10d3c` (feat)
2. **Task 2: Out-of-band n_restarts parallel-arm comparison (D-03)** - `2b2680ba` (feat)

_No TDD tasks in this plan; both are diagnostic one-off scripts per RESEARCH.md's Open
Question 2 recommendation, matching every prior pilot script in `scripts/analysis/`._

## Files Created/Modified
- `scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` - Multi-cell (8 symbols x 4
  tfs) real-data seed-stability diagnostic; samples first/middle/last walk-forward
  training-prefix boundaries per cell; corpus-wide headline is the MINIMUM
  `min_pairwise_agreement`, not an average; writes
  `cache/hmm_seed_stability_pilot_results.json`.
- `scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py` - D-03's two-block
  attribution comparison; implements the multi-restart walk-forward arm entirely inline
  (`_walk_forward_hmm_labels_multi_restart`); writes
  `cache/hmm_n_restarts_comparison_results.json`.

## Decisions Made
- **Numerical-failure handling added beyond the plan's literal text (Rule 1/2 -- bug/missing
  critical functionality):** neither script's action block explicitly anticipated a
  `LinAlgError` mid-EM-fit on a thin prefix, but this is a real failure mode encountered
  live while exercising `_hmm_seed_stability_check` and the inline multi-restart loop
  against real corpus data for the first time (exactly what REQ-5's "invoked-nowhere"
  concern was about). Both scripts now catch `(np.linalg.LinAlgError, ValueError)` per
  fit attempt and degrade gracefully (record as a hard stability failure) instead of
  crashing the whole multi-cell run. `services/regime_writer.py` itself is untouched --
  the catch lives entirely in the calling scripts, preserving the plan's "no production
  code path modified" constraint.
- **Worktree `.venv` symlink (Rule 3 -- blocking issue, not a package install):** this
  worktree has no gitignored `.venv` (a known GSD worktree gap -- see
  `feedback_gsd_worktree_venv_missing.md` in project memory), which blocked both running
  the verify commands and the repo's pre-commit ruff/black checks. Created a local,
  gitignored symlink `.venv -> /home/bg/dev/indicagent/.venv` (the main repo's existing,
  already-populated venv) rather than installing anything new. This is worktree-local
  housekeeping, not a code change, and is excluded from every commit (`.venv` is
  gitignored at the repo root).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Catch GaussianHMM covariance-singularity failures instead of crashing**
- **Found during:** Task 1 verify run (TLT/1d, first boundary) and confirmed again on
  SPY/1d (first and middle boundaries)
- **Issue:** `_hmm_seed_stability_check` and the inline multi-restart loop can raise
  `ValueError: 'covars' must be symmetric, positive-definite` (via hmmlearn's internal
  Cholesky decomposition) when fitting a full-covariance 5-state GaussianHMM on a thin
  (~504-obs) training prefix. Left unhandled, this crashes the entire multi-cell
  diagnostic on the very first boundary of the very first cell.
- **Fix:** Wrapped each fit call in `try/except (np.linalg.LinAlgError, ValueError)`.
  Seed-stability pilot: records the failing boundary as
  `min_pairwise_agreement=0.0` (below the 0.25 FAIL gate -- a fit crash IS the degenerate
  case this check exists to catch). n_restarts pilot: skips a failed candidate within the
  multi-restart loop (matching `_compute_symbol_tf`'s own per-seed independence), and
  aborts the whole cell with a printed reason if either `_walk_forward_hmm_labels` itself
  or every restart candidate for a segment fails.
- **Files modified:** both new scripts (not `services/regime_writer.py`)
- **Verification:** Re-ran Task 1's verify command (TLT/1d) -- completes cleanly with a
  `SEED STABILITY: TLT 1d: FAIL` verdict instead of a traceback. Re-ran against SPY/1d
  (3 boundaries) -- 2 numerical failures + 1 genuine low-agreement measurement
  (0.015 at the "last" boundary, 4788 obs), demonstrating the diagnostic surfaces real
  seed instability independent of the numerical-crash pathology.
- **Committed in:** `4dc10d3c` (Task 1), `2b2680ba` (Task 2)

**2. [Rule 3 - Blocking] Symlinked worktree `.venv` to the main repo's venv**
- **Found during:** Attempting to run Task 1's verify command
- **Issue:** This worktree has no `.venv` (gitignored, not checked out per-worktree);
  `.venv/bin/python` and the pre-commit hook's `${REPO_ROOT}/.venv/bin/ruff`/`black`
  lookups both failed.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv .venv` -- a worktree-local, gitignored
  symlink to the already-installed, already-populated main-repo venv. No new package was
  installed; this is not the package-install exclusion case (no `pip install` ran, no new
  dependency was added).
- **Files modified:** none (symlink is gitignored, does not appear in `git status`)
- **Verification:** `.venv/bin/python --version` resolves; pre-commit hook's ruff/black
  checks passed on both task commits.
- **Committed in:** not committed (gitignored, worktree-local only)

---

**Total deviations:** 2 auto-fixed (1 bug/missing-error-handling, 1 blocking
environment issue)
**Impact on plan:** Both fixes were necessary to complete the plan's own verify commands
as specified. No scope creep -- `services/regime_writer.py` remains untouched, matching
both the plan's and the threat model's "no production code path modified" requirement.

## Issues Encountered

**Task 2's literal verify command (`--symbols TLT --tf 1d --n-restarts 2 --n-boot 100`)
aborts rather than printing both verdict blocks, due to a real data-availability gap, not
a script bug.** `feature_vectors.regime` is entirely NULL for TLT/1d (0 of 2,381 rows) --
confirmed via direct query, not something either script can control. This is one of
several `(symbol, tf)` cells in the current corpus with all-NULL `regime` (also EEM/1d,
EEM/1h, and dozens of others across the 231-symbol universe), consistent with STATE.md's
in-progress universe-expansion backfill (2026-08-05/06) rather than any known deliberate
exclusion (TLT is not on `regime_writer.py`'s own documented reasoned-exclusion list,
which covers occupation-gate failures, not missing production data).

The script's abort path is itself correct per spec ("Abort a cell with a printed reason
when fewer than 50 bars overlap"), and did so: `block_a_overlap=0` printed, `ABORT:
insufficient overlap`, `D-03 ATTRIBUTION: No cells evaluated -- INCONCLUSIVE`, and
`cache/hmm_n_restarts_comparison_results.json` still written -- satisfying every acceptance
criterion except the literal "both blocks print" one for this specific symbol/tf. To
positively confirm the full two-block + D-03 ATTRIBUTION output path works end-to-end
(not just the abort path), the same command was re-run against GLD/1d (same 8-symbol pilot
scope, full production regime coverage: 4,798/4,798 rows) and produced Block A, Block B,
and the D-03 ATTRIBUTION line exactly as the acceptance criteria describe. Both runs'
transcripts are reflected in this summary; the plan's exact verify command was run
unmodified as specified.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both scripts are ready for plan 171-05 to invoke against the full pilot scope (8
  symbols x 4 tfs) and read their verdicts before the production `alpha.hmm.walk_forward.enabled`
  flip and the `feature_vectors.regime` NULL-out.
- Plan 171-05 must run `hmm_n_restarts_walk_forward_comparison_pilot.py` BEFORE any
  NULL-out of `feature_vectors.regime` -- this plan's Block A comparison depends on the
  retired full-history-fit production labels still being present.
- Plan 171-06's quarantine decision can consume `cache/hmm_seed_stability_pilot_results.json`
  directly (per-cell `verdict` field, `cell_min_pairwise_agreement`) once the full 8x4
  pilot run completes -- this plan only ran narrow smoke-test slices (TLT/1d, SPY/1d,
  GLD/1d) to verify correctness, not the full pilot scope.
- Known real data gap to account for when 171-05 runs the full 8x4 grid: TLT/1d, EEM/1d,
  and EEM/1h currently have zero production `regime` rows in `feature_vectors`, so
  Block A of the n_restarts comparison will abort for those specific cells regardless of
  script correctness -- not a blocker, but expected and should not be mistaken for a bug
  if seen again during the full run.

---
*Phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix*
*Completed: 2026-08-08*

## Self-Check: PASSED

- FOUND: scripts/analysis/hmm_walk_forward_seed_stability_pilot.py
- FOUND: scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py
- FOUND: .planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-04-SUMMARY.md
- FOUND commit: 4dc10d3c (Task 1)
- FOUND commit: 2b2680ba (Task 2)
- FOUND commit: af896f57 (SUMMARY, pre-em-dash-fix)
