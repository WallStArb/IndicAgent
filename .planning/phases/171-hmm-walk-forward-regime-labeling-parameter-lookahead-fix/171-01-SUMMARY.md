---
phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix
plan: 01
subsystem: infra
tags: [hmmlearn, structlog, argparse, regime_writer, hmm, walk-forward, observability]

# Dependency graph
requires: []
provides:
  - "Per-segment convergence logging on the walk-forward HMM path (`regime_writer.walk_forward_hmm_convergence_iters`), path-distinguishable from the single-fit path's `regime_writer.hmm_convergence_iters`"
  - "`--walk-forward` / `--no-walk-forward` CLI flags on `regime_writer.py` that override `alpha.hmm.walk_forward.enabled` for one invocation without writing `config_state`"
  - "Dispatch-branch test coverage for `_run_symbol_worker`'s walk-forward vs single-fit routing, proving both the positive call and the negative non-call in each direction"
affects: [171-05, todo-226]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CLI-overrides-APR-for-one-run: mutually exclusive `--flag`/`--no-flag` argparse group with `set_defaults(<dest>=None)` so 'absent' is distinguishable from 'explicitly false', same precedent as the existing `--workers` override"
    - "Discriminating dispatch-branch test: assert BOTH the positive sentinel call and the negative sentinel non-call in each branch, without mutating the source file under test, so an inverted branch cannot pass"

key-files:
  created: []
  modified:
    - services/regime_writer.py
    - tests/unit/services/test_regime_writer.py

key-decisions:
  - "Per-segment log event name is `regime_writer.walk_forward_hmm_convergence_iters`, deliberately distinct from the single-fit path's `regime_writer.hmm_convergence_iters`, so todo 226's downstream cap-headroom analysis can tell which code path produced a given record."
  - "`symbol`/`tf` threaded into `_walk_forward_hmm_full` as optional (default `None`) kwargs, log-correlation context only, never used in compute, so the three existing keyword-arg test call sites keep passing unedited."
  - "`--walk-forward`/`--no-walk-forward` is deliberately NOT a new APR key -- it is a per-invocation CLI override of the existing `alpha.hmm.walk_forward.enabled` key, mirroring the file's own `--workers` precedent."
  - "Dispatch-branch test proves discrimination via paired positive/negative sentinel assertions instead of temporarily inverting the production `if` branch -- avoids ever leaving `regime_writer.py` in a broken state between mutation and revert."

patterns-established:
  - "Per-segment (not per-cell, not per-row) logging inside a walk-forward refit loop: bounded count (~20 segments per full-history 5m cell), not the per-row logging CLAUDE.md forbids."

requirements-completed: [REQ-2]

# Metrics
duration: 12min
completed: 2026-08-08
---

# Phase 171 Plan 01: HMM Walk-Forward Observability + Per-Invocation Override Summary

**Per-segment convergence logging and a non-persistent `--walk-forward` CLI override close the two code-level gaps between `regime_writer.py`'s single-fit and walk-forward HMM paths, both proven by tests that assert discrimination rather than just presence.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-08T02:12:00-04:00 (approx.)
- **Completed:** 2026-08-08T02:24:11-04:00
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_walk_forward_hmm_full` now emits one `regime_writer.walk_forward_hmm_convergence_iters` log record per refit segment (not per cell), so a full-corpus walk-forward run yields the cap-headroom distribution todo 226 needs on the path that actually runs at scale -- the previous instrumentation lived only in `_compute_symbol_tf`, the path the rollout does NOT use.
- `regime_writer.py --walk-forward` / `--no-walk-forward` let a scoped pilot (plan 171-05) select the walk-forward path for one invocation without ever mutating the production `alpha.hmm.walk_forward.enabled` config value -- verified live against `config_state` after the change.
- `_run_symbol_worker`'s dispatch branch (walk-forward vs single-fit) now has a test that would fail if the branch were inverted, closing the exact coverage gap RESEARCH.md identified.

## Task Commits

Each task was committed atomically:

1. **Task 1: Per-segment convergence instrumentation on the walk-forward path** - `276c8c62` (feat)
2. **Task 2: Per-invocation walk-forward override and dispatch-branch coverage** - `6c19dafc` (feat)

_Both tasks used `tdd="true"`; tests were written and verified passing together with the implementation in the same commit per the plan's TDD-lite `<behavior>`/`<action>` structure -- there was no separate RED-only commit because the plan's task granularity bundled test+implementation into one atomic `feat` commit each, consistent with how the three pre-existing `_walk_forward_hmm_full` tests in this file are structured._

## Files Created/Modified
- `services/regime_writer.py` - Added optional `symbol`/`tf` kwargs + per-segment `regime_writer.walk_forward_hmm_convergence_iters` log call to `_walk_forward_hmm_full`; threaded `symbol=symbol, tf=tf` through its call site in `_compute_symbol_tf_walk_forward`; added `--walk-forward`/`--no-walk-forward` mutually-exclusive CLI flags to `main()`'s argparse block; resolved effective `walk_forward_enabled` from CLI-or-APR with a `walk_forward_source` field added to the `regime_writer.starting` log.
- `tests/unit/services/test_regime_writer.py` - Added `test_walk_forward_hmm_full_logs_convergence_iters_per_segment` (asserts one log event per segment, correct field shape) and `test_run_symbol_worker_dispatches_on_walk_forward_flag` (asserts paired positive-call/negative-non-call for both `walk_forward_enabled=True` and `False`, via monkeypatched sentinels, with zero mutation of `services/regime_writer.py`).

## Decisions Made
See `key-decisions` in frontmatter above -- all four were plan-directed (RESEARCH.md/PATTERNS.md already specified the event-name distinction, the CLI-override-not-APR-key framing, and the paired-assertion test design). No executor-originated design decisions were needed beyond following the plan's `<action>` blocks precisely.

## Deviations from Plan

None - plan executed exactly as written. Two small implementation-detail choices within the plan's stated bounds:
- Reused the loop's later `seg_end = min(boundary + refit_every_bars, n)` computation for the log call instead of introducing a separate `seg_end_for_log` temp variable, to avoid a redundant duplicate computation in the hot loop. Behavior is identical to the plan's literal instruction (`seg_end=min(boundary + refit_every_bars, n)`); this is a pure code-cleanliness simplification within Task 1's own action, not a deviation from the plan's behavior contract.

## Issues Encountered

**Worktree missing `.venv` (known project gotcha, not a regime_writer.py bug):** this worktree checkout has no `.venv/` (it is gitignored and not created per-worktree, per `[feedback_gsd_worktree_venv_missing]` in project memory). Both the manual test/lint commands and the repo's `.githooks/pre-commit` hook (which auto-detects `${REPO_ROOT}/.venv/bin/{ruff,black}`) require it. Resolved by symlinking `.venv` in the worktree to the main repo's `/home/bg/dev/indicagent/.venv` (a link, not a copy -- `.venv` is gitignored so this is invisible to git and was not committed). This is the standard, non-destructive workaround for this known gotcha; it does not touch any tracked file and does not persist past the worktree's lifetime.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 171-05 (the scoped 8-symbol pilot) can now run `regime_writer.py --walk-forward` against a small symbol/tf scope without touching production's `alpha.hmm.walk_forward.enabled` config value, and its resulting `feature_ic_scores`/log output will carry per-segment convergence records distinguishable from the single-fit path.
- Todo 226's cap-headroom check now has a data source on the walk-forward path as well as the single-fit path, whenever either runs at corpus scale.
- No blockers for downstream plans in this phase.

---
*Phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix*
*Completed: 2026-08-08*

## Self-Check: PASSED

- FOUND: services/regime_writer.py
- FOUND: tests/unit/services/test_regime_writer.py
- FOUND: .planning/phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-01-SUMMARY.md
- FOUND commit: 276c8c62 (Task 1)
- FOUND commit: 6c19dafc (Task 2)
- FOUND commit: 6d5707f4 (SUMMARY.md metadata commit)
