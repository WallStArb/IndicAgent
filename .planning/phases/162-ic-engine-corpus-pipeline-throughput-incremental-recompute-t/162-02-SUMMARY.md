---
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
plan: 02
subsystem: database
tags: [ic_engine, apr, threading, config, timescaledb]

# Dependency graph
requires:
  - phase: 162-01
    provides: "_compute_one_cross_sectional_cell / _subsample_and_rank (post-structural-extraction shape this plan edits)"
provides:
  - "services/ic_engine.py::ICEngineConfig.cross_sectional_bootstrap_threads -- per-tf dict[str, int], assembled in from_apr()"
  - "migration 250 -- alpha.ic.cross_sectional_bootstrap_threads.{5m,15m,1h,1d} APR keys"
affects: [162-03, 162-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-tf flat APR key dict-comprehension assembly (mirrors bootstrap_block_size)"

key-files:
  created:
    - production/migrations/250_ic_cross_sectional_bootstrap_threads_per_tf.sql
  modified:
    - services/ic_engine.py
    - src/intelligence/statistics/ic_math.py
    - tests/unit/test_ic_engine_parallelism.py

key-decisions:
  - "Split the two tasks into two commits at the exact hunk boundary the plan specifies (dict assembly in Task 1, call-site indexing in Task 2) rather than landing both in one commit -- required a git checkout + selective re-apply of edits since both tasks touch overlapping regions of the same file"
  - "5m seeded at 6 threads (largest cross-sectional cells, up to ~599K rows per migration 249's incident record); 15m/1h/1d seeded at 1 (serial) -- these cells finish in minutes and gain nothing from thread dispatch overhead"

requirements-completed: [SC-5]

# Metrics
duration: ~15min active work
completed: 2026-07-22
---

# Phase 162 Plan 02: ic_engine Per-TF Cross-Sectional Bootstrap Threads Summary

**`cross_sectional_bootstrap_threads` converted from a single scalar APR key to a per-tf dict (`{5m,15m,1h,1d}`), closing todo 133 -- 15m/1h/1d cross-sectional cells now default to serial (no thread-pool dispatch overhead) while 5m keeps its threaded speedup, with zero output change guaranteed by 162-01's precomputed resample-index matrix.**

## Performance

- **Duration:** ~15 min active work
- **Tasks:** 2/2 completed
- **Files modified:** 4 (3 modified, 1 created)

## Accomplishments

- Migration 250 seeds 4 flat `alpha.ic.cross_sectional_bootstrap_threads.{5m,15m,1h,1d}` APR keys (5m=6 `[initial_estimate]`, 15m/1h/1d=1 `[conventional]`), retiring the old scalar `infra.ic_engine.cross_sectional_bootstrap_threads` key (migration 232) with no remaining code reader.
- `ICEngineConfig.cross_sectional_bootstrap_threads` is now `dict[str, int]`, assembled in `from_apr()` via a dict-comprehension mirroring `bootstrap_block_size`'s existing pattern exactly.
- `_compute_one_cross_sectional_cell`'s `_circular_block_bootstrap_ic` call site now indexes `config.cross_sectional_bootstrap_threads[tf]`, matching `config.bootstrap_block_size[tf]` one argument over. The per-symbol path (`_compute_one_regime_cell`) is untouched -- it still hardcodes `max_workers=1` and never references this dict at all (verified by a new `inspect.getsource` test asserting absence).
- Thread count changes wall time only, never output -- this is guaranteed structurally by 162-01's precomputed resample-index matrix (`starts_matrix`, drawn once per scale before the feature-block loop), not re-derived or re-verified in this plan; the plan explicitly directed citing that invariant rather than re-proving it.
- Extended `test_ic_engine_parallelism.py` with 4 new tests: `from_apr()` producing the correct per-tf dict from stub APR overrides, `from_apr()` falling back to defaults when keys are absent (pre-migration safety), the cross-sectional cell function's source containing the `[tf]` subscript, and the per-symbol cell function's source never mentioning `cross_sectional_bootstrap_threads` at all. Also fixed the file's stale module docstring, which claimed the circular block bootstrap had been "replaced by Fisher z-transform CI" -- it is the circular block bootstrap that is live (`_subsample_and_rank` -> `_circular_block_bootstrap_ic`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Seed 4 per-tf bootstrap-thread APR keys and assemble them into a dict** - `f2f207d7` (feat)
2. **Task 2: Index the thread dict by tf at the bootstrap CI call site (output unchanged)** - `edfcc4a4` (feat)

**TDD note:** both tasks carried `tdd="true"`, but this plan's frontmatter `type` is `execute` (not `tdd`), so the strict plan-level RED/GREEN/REFACTOR gate-sequence enforcement does not apply -- same precedent as 162-01. Tests were written alongside each task's implementation and committed together per task (`feat` commits, not separate `test` -> `feat` pairs), since the assertions (dict-shape from a stub config, `inspect.getsource` subscript presence/absence) only have meaning once the target code exists in its final per-task form.

## Files Created/Modified

- `production/migrations/250_ic_cross_sectional_bootstrap_threads_per_tf.sql` - seeds 4 flat per-tf APR keys, config_schema + config_state + config_history triple (mirrors migration 249's pattern)
- `services/ic_engine.py` - `ICEngineConfig.cross_sectional_bootstrap_threads` field type change (int -> dict[str, int]) + updated comment; `from_apr()` dict-comprehension assembly; `_compute_one_cross_sectional_cell`'s docstring + call-site comment + the actual `max_workers=config.cross_sectional_bootstrap_threads[tf]` subscript
- `src/intelligence/statistics/ic_math.py` - two docstring updates (`_circular_block_bootstrap_ic`'s `max_workers` arg doc now cites the per-tf APR key pattern; `circular_block_bootstrap_ic_serial`'s docstring example now shows the `[tf]`-indexed call site it structurally guards against copying)
- `tests/unit/test_ic_engine_parallelism.py` - module docstring fix + 4 new tests (`_StubConfigService` helper, 2 `from_apr()` dict-shape tests, 2 `inspect.getsource` call-site-indexing tests)

## Decisions Made

- **Task-boundary commit splitting:** the plan's two tasks touch overlapping regions of `services/ic_engine.py` (the dataclass field/`from_apr()` in Task 1, the call site 1600 lines away in Task 2, plus a docstring a few lines above that call site). To land two genuinely atomic per-task commits rather than one combined commit, I applied Task 1's edits, ran its verify command, committed, then applied Task 2's edits on top, ran its verify command, and committed separately. This required one `git checkout -- <file>` + selective re-apply cycle per file (permitted under `destructive_git_prohibition` for a specific file the current task is actively editing).
- **Seed values:** 5m=6 (threaded), 15m/1h/1d=1 (serial) -- taken directly from the plan's own action text, which cites migration 249's incident record (5m cross-sectional cells up to ~599K rows) as the justification for keeping 5m threaded while flattening the other three timeframes to serial.

## Deviations from Plan

None - plan executed exactly as written. The `ic_math.py` docstring edits were explicitly implied by the plan's "old scalar key read removed" instruction (Task 1) and the `[tf]` indexing change (Task 2) -- both are direct, in-scope consequences of the field-type change, not new scope.

## Issues Encountered

- **Worktree base was stale at spawn time.** This worktree's branch had diverged from `435f5c7b` (the post-162-01-merge commit the plan depends on) -- `git merge-base HEAD 435f5c7b...` returned an earlier ancestor (`86d6f628`), meaning the worktree was created before 162-01 landed on `main`. Per the mandatory `worktree_branch_check` step, ran `git reset --hard 435f5c7b...` to align (sanctioned, not a self-recovery on a protected branch -- HEAD was and remained on `worktree-agent-ad96f7a79ff8e64f2` throughout).
- **No `.venv` in this worktree** (documented project gotcha, same as 162-01): symlinked `<worktree>/.venv -> /home/bg/dev/indicagent/.venv` to resolve the pre-commit hook's ruff/black tool discovery. Filesystem-only, not a tracked change.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **162-03 (fingerprint table + watermarks)** depends on this plan per 162-01's own "Next Phase Readiness" note: `_checkpoint_content_key()` hashes source bytes, and this plan's edits are now the final structural state of `_compute_one_cross_sectional_cell`'s relevant region for 162-03 to fingerprint against.
- **162-04 (equivalence harness)** is unaffected by this plan's scope (pure config/threading change, no algorithmic output change) but remains the correct home for the live-corpus bit-identical regression check that neither 162-01 nor this plan's sandbox could run.
- **Benchmark validation (SC-5's "within ~10% of measured serial wall time")** was explicitly out of scope for this plan per its own `<verification>` section -- it is a resource-contention-gated ops measurement (`ps aux | grep ic_engine` must be clear), not a unit test, and informs seed-value tuning rather than gating this plan's completion. Not run in this sandbox.
- No blockers. Full `tests/unit/` suite green (only 3 pre-existing, unrelated skips, unchanged from 162-01's baseline).

---
*Phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t*
*Plan: 02*
*Completed: 2026-07-22*

## Self-Check: PASSED

All 5 created/modified files confirmed present on disk (`test -f`). All 3
commit hashes (`f2f207d7`, `edfcc4a4`, `e033f432`) confirmed present in
`git log`. No missing items.
