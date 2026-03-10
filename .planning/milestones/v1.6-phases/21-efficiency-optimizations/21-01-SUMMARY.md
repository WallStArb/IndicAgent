---
phase: 21-efficiency-optimizations
plan: 01
subsystem: indicator
tags: [indicator_service, dataframe, cache, optimization, buffer-management]

# Dependency graph
requires:
  - phase: 18-financial-math-safety
    provides: indicator_service with asyncio lock infrastructure and plugin state isolation
provides:
  - services/indicator_service.py with lazy DataFrame cache invalidation
affects: [indicator_service, I1-pipeline-performance]

# Tech tracking
tech-stack:
  added: []
  patterns: [cache-invalidate-on-eviction, lazy-cache-rebuild, cache_invalidated-flag-pattern]

key-files:
  created:
    - tests/unit/services/test_indicator_service_buffer.py
  modified:
    - services/indicator_service.py

key-decisions:
  - "cache_invalidated flag pattern: track whether popitem() was called rather than unconditionally setting cache to None — eliminates redundant pd.DataFrame() construction on every bar append"
  - "Cache invalidation only on buffer eviction: _df_cache[key] = None occurs only when len(history) > _bar_history_max, not on every bar"

patterns-established:
  - "cache_invalidated flag: use boolean flag inside while loop to detect eviction, then conditionally invalidate"

requirements-completed: [EFF-01]

# Metrics
duration: 2min
completed: 2026-03-09
---

# Phase 21 Plan 01: DataFrame Cache Invalidation Optimization Summary

**Reduced indicator_service DataFrame rebuilds from every-bar to only-when-evicting: _df_cache invalidated only when buffer capacity is exceeded and oldest bar is removed**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-09T08:22:37Z
- **Completed:** 2026-03-09T08:24:54Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Eliminated redundant `pd.DataFrame()` construction on every bar append in `_process_single_bar()`
- Added `cache_invalidated` flag that is only set inside the eviction `while` loop
- Created 7 unit tests covering all cache-retain and cache-invalidate scenarios
- All 1359 tests pass with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Optimize DataFrame cache invalidation in indicator_service** - `54f4933` (feat)
2. **Task 2: Add unit tests for buffer management optimization** - `cb9635c` (test)

## Files Created/Modified
- `services/indicator_service.py` - `_process_single_bar()`: cache only invalidated when `cache_invalidated` flag is set (requires eviction from buffer)
- `tests/unit/services/test_indicator_service_buffer.py` - 7 unit tests for buffer cache behavior

## Decisions Made
- `cache_invalidated` flag approach: cleaner than checking `len(history) == _bar_history_max` after the fact; the flag is set inside the `while` loop that calls `popitem()`, making the cause-effect relationship explicit
- `_get_df()` unchanged: lazy rebuild on cache miss is correct; no change needed to the reader side

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 21 Plan 01 complete; indicator_service DataFrame cache now invalidated only on eviction
- No blockers; remaining plans in phase 21 can proceed

---
*Phase: 21-efficiency-optimizations*
*Completed: 2026-03-09*
