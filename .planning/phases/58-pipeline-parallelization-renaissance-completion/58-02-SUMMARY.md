---
phase: 58-pipeline-parallelization-renaissance-completion
plan: 02
subsystem: testing
tags: [pytest, prometheus, plugin-metrics, determinism, exception-isolation, asyncio, thread-pool]

# Dependency graph
requires:
  - phase: 58-01
    provides: PLUGIN_DURATION_MS Histogram, PLUGIN_ERRORS_TOTAL Counter, _timed_plugin_call wrapper, _collect_plugin_results with tier+metrics wiring
provides:
  - Determinism proof: 100 bars sequential == parallel for I1 and I7 (tests/unit/test_pipeline_determinism.py)
  - Exception isolation proof: plugin failures never crash pipeline; graceful degradation with labeled metric firing (tests/unit/test_pipeline_exception_isolation.py)
affects: [58-03-PLAN, future ML validation, signal quality audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD test structure: _make_agent() via __new__ pattern, _deterministic_plugin(), _failing_plugin() helpers reused across test files"
    - "Patch at services.intelligence_pipeline_agent.PLUGIN_ERRORS_TOTAL (import-site) not src.observability.metrics — correctly targets the module namespace"
    - "I7 exception isolation: patch _build_features_from_event + all gate functions to isolate plugin failure from ranking logic"

key-files:
  created:
    - tests/unit/test_pipeline_determinism.py
    - tests/unit/test_pipeline_exception_isolation.py
  modified: []

key-decisions:
  - "Patch metrics at services.intelligence_pipeline_agent.PLUGIN_ERRORS_TOTAL — the module imports them at module load; patching at source (src.observability.metrics) does not intercept already-bound references"
  - "apply_quality_gate/regime_gate patched with side_effect=lambda sigs, *a, **kw: sigs for transparent pass-through in I7 tests — preserves signal count invariant"
  - "test_thread_pool_size_configurable creates explicit executor with max_workers=64 rather than going through __init__ — validates the pool size attribute is readable, without needing full Settings DI"

patterns-established:
  - "Per-plan _make_agent() copy: each test module is self-contained with its own _make_agent helper — avoids cross-module state contamination"
  - "100-iteration determinism check: assert all(r == results[0] for r in results[1:]) — canonical pattern for proving output stability"

requirements-completed: [PIPE-04, PIPE-05, PIPE-01, PIPE-02]

# Metrics
duration: 8min
completed: 2026-04-02
---

# Phase 58 Plan 02: Pipeline Correctness Tests Summary

**Determinism and exception isolation proofs: 10 new tests confirm 100-bar sequential==parallel equivalence for I1/I7, plugin crash containment, PLUGIN_ERRORS_TOTAL/PLUGIN_DURATION_MS metric firing**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-02T08:20:00Z
- **Completed:** 2026-04-02T08:28:00Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments
- Created `test_pipeline_determinism.py` with 4 tests proving I1 and I7 produce identical output across 100 iterations and that parallel output matches direct sequential calls within floating-point tolerance
- Created `test_pipeline_exception_isolation.py` with 6 tests covering single/all plugin failure scenarios, PLUGIN_ERRORS_TOTAL counter firing, PLUGIN_DURATION_MS histogram recording, and partial output propagation
- All 13 pipeline tests (3 existing + 4 determinism + 6 isolation) pass cleanly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create determinism test — sequential vs parallel output equivalence** - `c9f85cf` (test)
2. **Task 2: Create exception isolation test — plugin failure graceful degradation** - `9783629` (test)

## Files Created/Modified
- `tests/unit/test_pipeline_determinism.py` - 4 tests: 100-bar I1 determinism, parallel==sequential comparison, 100-bar I7 determinism, thread pool size configurability
- `tests/unit/test_pipeline_exception_isolation.py` - 6 tests: single/all I1 failure, I7 single failure, PLUGIN_ERRORS_TOTAL/PLUGIN_DURATION_MS metric assertions, partial key propagation

## Decisions Made
- Patch at `services.intelligence_pipeline_agent.PLUGIN_ERRORS_TOTAL` (import-site), not at `src.observability.metrics.PLUGIN_ERRORS_TOTAL` — the module already bound the reference at import time; patching source does not intercept calls in the agent module
- Gate functions patched with `side_effect=lambda sigs, *a, **kw: sigs` for transparent pass-through in I7 tests — keeps signal count predictable without duplicating gate logic
- Thread pool test creates explicit executor at max_workers=64 rather than going through full Settings DI — validates the pool size attribute is readable without mock complexity

## Deviations from Plan

**Deviation: Merged worktree before Plan 01 changes**
- **Found during:** Task 1 setup
- **Issue:** This parallel agent worktree branched from main before Plan 01's metrics/settings changes were committed; PLUGIN_ERRORS_TOTAL and _timed_plugin_call were absent
- **Fix:** `git merge main --no-edit` to fast-forward the worktree branch with Plan 01's commits
- **Files modified:** All Plan 01 files now present (src/observability/metrics.py, src/config/settings.py, services/intelligence_pipeline_agent.py)
- **Verification:** All 3 Plan 01 parallelization tests pass after merge

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking: missing prerequisite changes)
**Impact on plan:** Required worktree update to access Plan 01 interfaces. No scope creep.

## Issues Encountered
None — after merging Plan 01 changes, all tests passed on first run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03 (systemd/deployment) can proceed: all correctness proofs are in place
- PIPE-04 and PIPE-05 requirements closed
- All 13 pipeline tests are green and form the regression baseline

## Self-Check: PASSED

- `tests/unit/test_pipeline_determinism.py` exists: FOUND
- `tests/unit/test_pipeline_exception_isolation.py` exists: FOUND
- Task commits: c9f85cf, 9783629 exist in git log
- All 13 tests pass: VERIFIED

---
*Phase: 58-pipeline-parallelization-renaissance-completion*
*Completed: 2026-04-02*
