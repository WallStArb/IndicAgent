---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
plan: 05
subsystem: docs
tags: [documentation, itr, apr, todos, phase-close]

# Dependency graph
requires:
  - phase: 175-01
    provides: instrument_tags eleven Pass 4 evidence columns, instrument_tags_active view, discovery_state CHECK constraint, eleven alpha.tag_calibrator.materiality.* APR keys (migration 346)
  - phase: 175-02
    provides: partial_loading/partial_loading_ci_low/sign_stable_window_count/partial_loading_null_arm_p statistical kernels in factor_math.py
  - phase: 175-03
    provides: MaterialityConfig, decide_materiality, is_materiality_eligible, measure_partial_loadings (services/tag_calibrator.py Pass 4)
  - phase: 175-04
    provides: scripts/analysis/itr_materiality_shadow_diagnostic.py and its first live measured report against the corpus
provides:
  - "docs/foundation/instrument-tag-registry.md: canonical 4-pass ITR spec, eleven-column schema, eleven-key APR namespace, Pass 4/Read contract sections, three updated Known Gaps"
  - "docs/foundation/apr-calibration-backlog.md: ten new [initial_estimate] materiality threshold rows plus the sign-stability sliding-bar resolution, pointed at 175-03-PLAN.md/175-04-SUMMARY.md"
  - "CLAUDE.md's ITR paragraph extended to name the materiality filter and its shadow-mode status; Version bumped 5.55.5 -> 5.55.6"
  - "Todos 125/126 closed (completed/, git renames) with resolution records; 126's stale equity_regime_model.py reference corrected to breadth_vol.py"
  - "Todo 380 re-scoped to the remaining consumer-cutover decision; still tracked in PRIORITIES.md"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - docs/foundation/instrument-tag-registry.md
    - docs/foundation/apr-calibration-backlog.md
    - CLAUDE.md
    - .planning/todos/PRIORITIES.md
    - .planning/todos/deferred/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-collision.md
  renamed:
    - .planning/todos/pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md -> .planning/todos/completed/125-tag-calibrator-discovery-oos-gate-not-enforced.md
    - .planning/todos/pending/126-instrument-tags-valid-to-no-consumer-contract.md -> .planning/todos/completed/126-instrument-tags-valid-to-no-consumer-contract.md

key-decisions:
  - "Kept the em-dash count in instrument-tag-registry.md at its pre-task value (44) by writing all new prose with '--' instead of '—', including one diagram line that initially used an em dash to match the existing Pass 1/2/3 diagram style and had to be reworded to a plain hyphen to hold the acceptance criterion"
  - "Trimmed todo 126's resolution section from an initial ~63-line draft to ~15 lines after discovering the larger version dropped git's rename-similarity score below the 50% default threshold, causing git status to report an add+delete pair instead of a rename (R) -- the acceptance criterion required R detection under bare `git status --porcelain`, so content density took priority over exhaustiveness"
  - "Cited only the two headline numbers from 175-04-SUMMARY.md (2170 measured, 222 passing) plus the '0 symbols admitted' finding as the ITR spec's 'current empirical picture' -- did not attempt to reconcile the SQL verification query's differently-scoped 182/469 counts (source='empirical' only) against the TagCalibrator log's 222/2263 (all sources), since the plan's acceptance criterion only requires every cited number to appear verbatim in 175-04-SUMMARY.md, not a full reconciliation"

requirements-completed: [P175-04, P175-06, P175-07, P175-08]

# Metrics
duration: ~35min
completed: 2026-09-23
---

# Phase 175 Plan 05: ITR Materiality Documentation and Todo Closure Summary

**Brought the canonical ITR spec, the APR calibration backlog, and CLAUDE.md in line with the shipped 4-pass TagCalibrator engine, closed todos 125/126 with resolution records (correcting 126's stale file reference along the way), and re-scoped todo 380 to the remaining consumer-cutover decision -- documentation-only, zero code changes.**

## Worktree base correction

The worktree's HEAD started on a stale, unrelated commit chain (`525cdae6d`, an `ic_engine`
chunk-size fix from a different session) that was not an ancestor of the orchestrator-specified
wave base `83af9e5c7`. Per the mandated `worktree_branch_check` protocol this is an explicit,
authorized correction: `git reset --hard 83af9e5c7` was run (confirmed zero uncommitted changes
beforehand), HEAD verified to land exactly on the expected commit, and execution proceeded from
there. `.venv` was also missing (known GSD worktree gotcha -- gitignored, not created per
worktree) -- symlinked to the main repo's `.venv` so `pytest` could run.

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-09-23
- **Tasks:** 2
- **Files modified:** 4 (docs/foundation/instrument-tag-registry.md, docs/foundation/apr-calibration-backlog.md, CLAUDE.md, .planning/todos/PRIORITIES.md, .planning/todos/pending/380-...md)
- **Files renamed:** 2 (todos 125, 126 moved pending/ -> completed/)

## Accomplishments

- `docs/foundation/instrument-tag-registry.md`: every "three-pass" reference changed to "4-pass"; a full new Pass 4 subsection documents the control-set construction and its two F6.1/CR-01-derived exclusions, ΔR² as the incremental-R² definition (R-06), the discrete sign-stability step at n=1008 (R-07), the D-06 null arm, and the D-01a measurement universe; the `instrument_tags` schema table gained all eleven Pass 4 evidence columns; a new eleven-key `alpha.tag_calibrator.materiality.*` APR table and a new "Read contract" section (`instrument_tags_active`, `is_materiality_eligible()`) were added; all three Known Gaps entries were rewritten to accurate current status (125 RESOLVED, 126 RESOLVED-but-not-cut-over, sensitivity/macro_driver rewritten to cite the live shadow measurement)
- `docs/foundation/apr-calibration-backlog.md`: ten new Section 1 rows, one per materiality threshold key, each citing the plan 04 live GATE ATTRIBUTION counts as the first real evidence of which gate binds; a dedicated paragraph records the sign-stability sliding-bar resolution with named pointers to `175-03-PLAN.md` § R-07 and `175-04-SUMMARY.md` § NEAR MISS; `Last Updated` bumped to 2026-09-23
- `CLAUDE.md`'s ITR paragraph extended with the Pass 4/`is_materiality_eligible()`/shadow-mode sentence; `Version:` bumped 5.55.5 -> 5.55.6
- Todo 125: `## Resolution (2026-09-18, phase 175)` section records the typed-column promotion (migration 346), the retained-JSONB decision backed by the repo-wide `grep -rn "discovery_state|first_measured_at" src/ services/ scripts/` sweep (zero other readers found), and the closing test name
- Todo 126: `## Resolution (2026-09-18, phase 175)` section records the `instrument_tags_active` view and `is_materiality_eligible()`'s code-level `valid_to` re-check, and corrects the stale `equity_regime_model.py:289` citation to `breadth_vol.py` (reached via `cross_sectional_regime_model.py`'s group resolution) without editing the original body text
- Both todo files moved to `completed/` via `git mv`, staged individually (`git add -- <path>` per file) per CLAUDE.md's multi-pathspec gotcha, and confirmed as git renames (`R`, not add+delete) in `git status --porcelain` both before and after commit
- `PRIORITIES.md`: 125/126 rows removed entirely (no surrounding prose referenced them by number); 380's row rewritten to summarize what shipped and re-scope the remaining open item to the consumer-cutover decision
- Todo 380 itself: appended `## Phase 175 status (2026-09-18)` recording what shipped (Pass 4, migration 346, eleven APR keys, the diagnostic script, todos 125/126 closed) and what did not (any consumer query change), restating Part 2 (`eq_*` naming) needs no further action
- `.venv/bin/pytest tests/unit/test_todo_priorities_link_integrity.py -x -q` and `.venv/bin/pytest tests/unit/ -q` both green

## Task Commits

1. **Task 1: Update the ITR canonical spec, the APR calibration backlog, and CLAUDE.md** - `193b8c9dd` (docs)
2. **Task 2: Close todos 125 and 126, re-scope todo 380, keep PRIORITIES.md link integrity** - `b2bc962ee` (docs)

## Files Created/Modified

- `docs/foundation/instrument-tag-registry.md` - 4-pass description, eleven-column schema extension, Pass 4 subsection, eleven-key APR table, Read contract section, three rewritten Known Gaps, `Last Updated` bump
- `docs/foundation/apr-calibration-backlog.md` - ten new Section 1 rows, sign-stability resolution paragraph, `Last Updated` bump
- `CLAUDE.md` - extended ITR paragraph, `Version:` bump
- `.planning/todos/completed/125-tag-calibrator-discovery-oos-gate-not-enforced.md` (renamed from pending/) - resolution section appended
- `.planning/todos/completed/126-instrument-tags-valid-to-no-consumer-contract.md` (renamed from pending/) - resolution section appended, stale-path correction recorded
- `.planning/todos/PRIORITIES.md` - 125/126 rows removed, 380's row rewritten
- `.planning/todos/deferred/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-collision.md` - `## Phase 175 status (2026-09-18)` section appended

## Decisions Made

- All prose additions used `--` rather than `—` throughout, matching the project's writing-style rule and holding the em-dash-count-does-not-increase acceptance criterion at exactly 44 (one diagram line initially used `—` to match the existing Pass 1/2/3 diagram formatting and had to be reworded to a plain hyphen)
- Todo 126's resolution section was rewritten once, shorter, after the first draft (~63 new lines against a 31-line original) pushed git's content-similarity score below the 50% default rename-detection threshold -- `git status` reported it as an add+delete pair instead of a rename (`R`) until the section was trimmed to ~15 lines, which restored 64% similarity and satisfied the plan's literal `git status --porcelain` acceptance criterion
- Updated all three Known Gaps entries (not just the two the plan's action text named explicitly) for internal consistency: the plan named the `discovery_oos_days` gap (mark RESOLVED) and the sensitivity/macro_driver gap (rewrite) directly; the third existing gap (`valid_to` not filtered, todo 126's finding) was also updated to RESOLVED-but-not-cut-over, since leaving it stale while todo 126 closes in the same plan would have left the doc self-contradictory

## Deviations from Plan

None beyond the two mechanical corrections documented above under Decisions Made (em-dash
wording on one diagram line; todo 126's resolution-section length for rename-detection).
Both are Rule 1 territory -- the plan's own acceptance criteria required these exact outcomes
(em-dash count held, `git status` showing `R`), and the first draft of each didn't achieve
them. No architectural changes, no scope additions beyond the plan's two tasks.

## Issues Encountered

- `.venv` missing in the worktree (known GSD gotcha) -- symlinked to the main repo's `.venv`, itself gitignored and never staged.
- Worktree HEAD started on a stale commit chain unrelated to this phase's wave base -- corrected via the mandated `worktree_branch_check` reset, documented above.

## User Setup Required

None - no external service configuration required. Documentation-only plan.

## Next Phase Readiness

- This is the phase's final plan (wave 4 of 4). All five plans (175-01 through 175-05) are
  now complete: migration 346 + APR keys (01), factor-math kernels (02), TagCalibrator Pass 4
  integration (03), the shadow diagnostic and its first live run (04), and this plan's
  documentation/todo closure (05).
- Phase 175 ships shadow-mode measurement only (D-03) -- no live consumer (`breadth_vol.py`,
  `cross_sectional_regime_model.py`) was changed at any point in this phase. The remaining
  open item, tracked by todo 380, is the consumer-cutover decision, gated on the plan 04
  shadow report (0 symbols currently admitted under the seeded `[initial_estimate]`
  thresholds) plus a separate, later D-07 cross-AI review of that report and the user's own
  review -- explicitly out of scope for this phase.
- No blockers. P175-08 (the pre-execution D-07 plan-set review) is a process gate that cleared
  before Wave 1 started, per `175-REVIEWS.md` and `.planning/STATE.md`'s Phase Summary entry
  for Phase 175 -- not something this plan or any plan in this phase discharges directly.

---
*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: docs/foundation/instrument-tag-registry.md
- FOUND: docs/foundation/apr-calibration-backlog.md
- FOUND: .planning/todos/completed/125-tag-calibrator-discovery-oos-gate-not-enforced.md
- FOUND: .planning/todos/completed/126-instrument-tags-valid-to-no-consumer-contract.md
- FOUND: .planning/phases/175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro/175-05-SUMMARY.md
- FOUND: commit 193b8c9dd (Task 1)
- FOUND: commit b2bc962ee (Task 2)
- FOUND: commit 65431a2a6 (SUMMARY.md)
