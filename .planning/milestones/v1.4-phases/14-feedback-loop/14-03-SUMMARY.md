---
phase: 14-feedback-loop
plan: 03
subsystem: signal-generation
tags: [aggregator, perf-weights, redis, feedback-loop, signal-generator]

requires:
  - phase: 14-01
    provides: nightly performance update job writing setup_performance:weights to Redis
  - phase: 14-02
    provides: setup_performance_weights_cache() stream key helper already in stream_keys.py

provides:
  - _build_all_ranked() extended with perf_weights param and adjusted_rank on each signal dict
  - aggregate() gains perf_weights kwarg and passes through to _build_all_ranked()
  - SignalGeneratorService._perf_weights attr + _load_perf_weights() + _perf_weights_refresh_loop()
  - perf_weights passed to aggregate() on every _process_bar() call

affects: [signal-lifecycle, feature-store, dashboard]

tech-stack:
  added: []
  patterns:
    - "shutdown_event.wait(timeout=N) pattern for background refresh loops with clean shutdown"
    - "Class-level attribute default for __new__ testability (CLAUDE.md pattern)"
    - "adjusted_rank = composite_rank * perf_multiplier with ascending sort (lower = higher priority)"

key-files:
  created: []
  modified:
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py

key-decisions:
  - "Sort by adjusted_rank ASCENDING (lower = higher priority): tests are authoritative over plan text which said DESCENDING"
  - "Class-level _perf_weights = {} default on SignalGeneratorService enables hasattr() in __new__ tests"
  - "shutdown_event added to SignalGeneratorService for clean _perf_weights_refresh_loop termination"
  - "perf_multiplier 0.5 = outperformer (boosts rank by halving composite_rank); 1.5 = underperformer (penalizes)"

patterns-established:
  - "Neutral multiplier 1.0 for setups absent from perf_weights — never 0, never suppressed"
  - "_sort_by_priority() fallback uses negative SETUP_PRIORITY for ascending sort compatibility"

requirements-completed: [FEED-03]

duration: 25min
completed: 2026-03-06
---

# Phase 14 Plan 03: Perf Multiplier Wiring Summary

**adjusted_rank = composite_rank * perf_multiplier injected into aggregator ranking; SignalGeneratorService loads weights from Redis at startup and refreshes every 60 minutes**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-06T22:10:00Z
- **Completed:** 2026-03-06T22:35:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_build_all_ranked()` extended with optional `perf_weights` param: assigns `composite_rank` (1-based, all plugins) and `adjusted_rank` (composite_rank * perf_multiplier), sorts ascending by adjusted_rank
- `aggregate()` gains `perf_weights` kwarg and threads it through to `_build_all_ranked()`
- `_sort_by_priority()` helpers in both `_aggregate_via_cis` and `_aggregate_fallback` updated to sort ascending (using negative SETUP_PRIORITY fallback for backward compat)
- `SignalGeneratorService` gains `_perf_weights: dict`, `_load_perf_weights()`, `_perf_weights_refresh_loop()`, and `shutdown_event` for clean termination
- Perf weights loaded at startup and passed to `aggregate()` on every bar

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend aggregator _build_all_ranked() with perf_weights param** - `1e5e1c4` (feat)
2. **Task 2: Add perf_weights support to signal_generator_service** - `323fbdf` (feat)

## Files Created/Modified
- `src/intelligence/trading/aggregator.py` - _build_all_ranked() with perf_weights + adjusted_rank; aggregate() kwarg; updated _sort_by_priority() helpers
- `services/signal_generator_service.py` - _perf_weights attr, _load_perf_weights(), _perf_weights_refresh_loop(), shutdown_event, aggregate() call wired

## Decisions Made
- Sort order is ASCENDING by adjusted_rank (lower = higher priority). The plan text said DESCENDING but the RED test suite is authoritative: `assert adjusted_ranks == sorted(adjusted_ranks)` unambiguously requires ascending. Tests win.
- Added `_perf_weights: dict[str, float] = {}` as class-level attribute to satisfy the `__new__`-pattern test that calls `hasattr()` on a bare instance without `__init__`. This follows the CLAUDE.md pattern for service test infrastructure.
- `shutdown_event = asyncio.Event()` added to `__init__` and `set()` in `stop()`. Required by the refresh loop's `asyncio.wait_for(shutdown_event.wait(), timeout=3600)` pattern for clean termination.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sort order corrected from DESCENDING to ASCENDING**
- **Found during:** Task 1 (verification against test suite)
- **Issue:** Plan must_haves and action steps specified `reverse=True` (DESCENDING), but RED tests assert `adjusted_ranks == sorted(adjusted_ranks)` (ascending) and expect outperformer with multiplier=0.5 to rank first via lower adjusted_rank
- **Fix:** Used `sorted(with_ranks, key=lambda s: s["adjusted_rank"])` without `reverse=True`; updated `_sort_by_priority()` fallback to use negative SETUP_PRIORITY so higher-priority plugins still sort first in ascending order
- **Files modified:** src/intelligence/trading/aggregator.py
- **Verification:** All 8 test_aggregator_perf.py tests pass + all 41 existing test_aggregator.py tests pass
- **Committed in:** 1e5e1c4 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug: sort direction contradicted by tests)
**Impact on plan:** Necessary correctness fix. Tests are the spec; plan text was internally inconsistent. No scope creep.

## Issues Encountered
- `setup_performance_weights_cache` function already existed in `stream_keys.py` (added by Plan 02) — no action needed, imported directly.

## Next Phase Readiness
- FEED-03 complete: perf multiplier flows end-to-end from nightly job (FEED-02) → Redis → aggregator ranking on every bar
- Phase 14 Feedback Loop complete: FEED-01 (outcome writer), FEED-02 (nightly perf job), FEED-03 (ranking wired)
- Ready for Phase 15: Validated Alpha

---
*Phase: 14-feedback-loop*
*Completed: 2026-03-06*
