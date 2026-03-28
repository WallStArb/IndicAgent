---
phase: 48-signal-generator-warmup-seed
plan: 01
subsystem: [services, testing]
tags: [warmup, seed, bar-history, db-query, signal-generator]

# Dependency graph
requires:
  - phase: 47
    provides: signal_ledger, intelligence_features tables
provides:
  - DB warmup seed for signal_generator_service BarHistory
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [startup-seeding, graceful-fallback]

key-files:
  created: []
  modified: [services/signal_generator_service.py, tests/unit/service_tests/test_signal_generator_service.py]

key-decisions:
  - "Query intelligence_features not market_data_ohlcv (has bar JSONB column)"
  - "Graceful fallback to live warmup if DB unavailable"
  - "Process rows in reversed DESC order for chronological BarHistory"

patterns-established:
  - "DB seed method: query → reconstruct BarMessage → append to BarHistory"
  - "Fault tolerance: log WARNING and proceed on DB failure"

requirements-completed: []

# Metrics
duration: 30min
completed: 2026-03-23
---

# Phase 48: Signal Generator Warmup Seed Summary

**DB warmup seed on startup eliminates 50-minute signal processing delay after service restart**

## Performance

- **Duration:** 30 min
- **Started:** 2026-03-23T12:00:00Z
- **Completed:** 2026-03-23T12:30:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Restored DB warmup seed removed in Phase 26 BarHistory refactoring
- BarHistory now seeded with last 50 bars per (symbol, tf) on startup
- Signal generator processes signals immediately instead of waiting 50+ minutes
- Graceful degradation if DB unavailable (falls back to live warmup)

## Task Commits

Each task was committed atomically:

1. **Task 1: DB warmup seed implementation** - `73d5d17` (feat)

**Plan metadata:** N/A (standalone warmup seed fix)

## Files Created/Modified
- `services/signal_generator_service.py` - Added `_seed_bar_history_from_db()` method, called in `start()` after DB connection
- `tests/unit/service_tests/test_signal_generator_service.py` - Added 4 unit tests for warmup seed functionality

## Decisions Made
- Query `intelligence_features` table (has `bar` JSONB column) not `market_data_ohlcv`
- Use indexed query on `(symbol, tf, ts DESC)` - already exists as `idx_intel_features_sym_tf_ts`
- Process rows in reversed order (oldest first) to maintain chronological order in BarHistory
- Mark seeded bars with `source="ibkr_seed"` for observability
- Graceful fallback: log WARNING and proceed with empty BarHistory if DB fails

## Deviations from Plan

None - plan executed exactly as specified.

## Issues Encountered

- **Test session_id validation:** Initial test used `session_id="E"` but Pydantic enum requires known values like `"futures_24_5"`. Fixed by updating test to use valid session_id.
- **Mock row order:** Test initially had mock rows in ASC order, but SQL query returns DESC order. Fixed by reversing mock rows to match actual DB behavior.

## User Setup Required

None - no external service configuration required. Service will automatically seed from existing `intelligence_features` data on next restart.

## Next Phase Readiness

- Phase 48 complete, bars_processed=0 issue resolved
- Ready for Phase 49: DB performance optimization
- No blockers or concerns

---
*Phase: 48-signal-generator-warmup-seed*
*Completed: 2026-03-23*
