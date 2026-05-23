---
phase: 091-instrument-registry
plan: "02"
subsystem: database
tags: [asyncpg, listen-notify, cache, instruments, pipeline]

# Dependency graph
requires:
  - phase: 091-01
    provides: "instruments table trigger (trg_instruments_notify) installed via SQL"
provides:
  - "CacheManager.start_instruments_listener() returning asyncio.Task"
  - "_run_instruments_listener() with reconnect backoff on dedicated asyncpg connection"
  - "_on_instrument_notify() sync callback scheduling async cache reload"
  - "_reload_instruments_cache() with lazy invalidate_active_contracts_cache import"
  - "_instrument_from_row() module-level helper for DB row to Instrument construction"
  - "intelligence_pipeline_agent wires listener as 7th background task"
affects: [091-03, 091-04, 091-05, 091-06]

# Tech tracking
tech-stack:
  added: [asyncpg (direct LISTEN/NOTIFY connection)]
  patterns:
    - "Dedicated asyncpg.connect() for LISTEN (not pool context manager) to avoid subscription release"
    - "Sync callback + asyncio.get_event_loop().call_soon_threadsafe + asyncio.ensure_future for async scheduling from sync NOTIFY callback"
    - "Lazy import of invalidate_active_contracts_cache inside function to avoid circular import"
    - "Infinite retry loop with CancelledError re-raise and 5s backoff on other exceptions"

key-files:
  created: []
  modified:
    - src/intelligence/pipeline/cache_manager.py
    - services/intelligence_pipeline_agent.py
    - tests/unit/pipeline_tests/test_cache_manager.py

key-decisions:
  - "Use asyncpg.connect() (raw dedicated connection) not pool acquire for LISTEN - pool context manager releases connection on exit, destroying the subscription"
  - "_on_instrument_notify uses call_soon_threadsafe + ensure_future - callback is sync on event loop thread; ensure_future schedules coroutine without blocking"
  - "Lazy import of invalidate_active_contracts_cache inside _reload_instruments_cache to avoid circular import at module level"
  - "_reload_instruments_cache logs at ERROR (not WARNING) on failure and leaves _instruments_cache untouched so pipeline continues on last good state"

patterns-established:
  - "LISTEN listener task follows same lifecycle as refresh loop tasks: start_*() returns asyncio.Task, caller appends to _background_tasks with done_callback discard"

requirements-completed: [INST-03]

# Metrics
duration: 12min
completed: 2026-05-19
---

# Phase 091 Plan 02: Instrument Registry LISTEN/NOTIFY Consumer Summary

**asyncpg LISTEN consumer on dedicated connection, 5s reconnect backoff, fires invalidate_active_contracts_cache() within 1s of instruments table change**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-19T21:37:00Z
- **Completed:** 2026-05-19T21:49:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Added four methods to CacheManager: start_instruments_listener(), _run_instruments_listener(), _on_instrument_notify(), _reload_instruments_cache()
- Added _instrument_from_row() module-level helper that correctly reads FX full symbol from contract_details.symbol
- Wired listener as the 7th background task in intelligence_pipeline_agent._setup()
- 3 new unit tests covering: task creation, invalidate call, and notify-to-reload scheduling

## Task Commits

1. **Task 1: Add LISTEN/NOTIFY consumer methods to CacheManager** - `608cf304` (feat)
2. **Task 2: Wire start_instruments_listener() into intelligence_pipeline_agent** - `4cbebdfe` (feat)
3. **Task 3: Add unit tests for new CacheManager listener methods** - `e3048c4b` (test)

## Files Created/Modified
- `src/intelligence/pipeline/cache_manager.py` - Added asyncpg import, _instrument_from_row() helper, _instruments_cache attr, and 4 listener methods
- `services/intelligence_pipeline_agent.py` - Added listener task wire-up after start_refresh_loops() block
- `tests/unit/pipeline_tests/test_cache_manager.py` - Added 3 tests for listener task, invalidate call, and notify callback

## Decisions Made
- Used `asyncio.get_event_loop().call_soon_threadsafe()` in the sync notify callback rather than `asyncio.create_task()` directly - the asyncpg callback is already on the event loop thread, so ensure_future is the correct idiom for scheduling from a sync context
- `_reload_instruments_cache` logs at ERROR (not WARNING) on failure per acceptance criteria, and leaves `_instruments_cache` intact so pipeline continues on last good state
- Lazy import of `invalidate_active_contracts_cache` inside `_reload_instruments_cache` avoids a circular import: cache_manager imports from settings would create a circular dependency at module load time

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- New async tests initially failed because the file uses explicit `@pytest.mark.asyncio` decorators (not relying on `asyncio_mode=auto`). Fixed by adding the decorator to new async tests.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- INST-03 complete: pipeline picks up instrument changes within 1s via LISTEN/NOTIFY
- Ready for 091-03 (settings.py decomposition) which removes hardcoded contracts
- The _instruments_cache populated here will be consumed by get_active_contracts() after D-03 flip in 091-03

---
*Phase: 091-instrument-registry*
*Completed: 2026-05-19*
