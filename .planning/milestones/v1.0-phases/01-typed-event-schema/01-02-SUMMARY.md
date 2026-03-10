---
phase: 01-typed-event-schema
plan: 02
subsystem: api
tags: [pydantic, redis, typescript, sse, intelligence-bus, typed-events]

# Dependency graph
requires:
  - phase: 01-01
    provides: "IntelligenceEvent Pydantic schema and publisher migration"
provides:
  - "signal_generator_service.py consuming typed IntelligenceEvent via model_validate_json()"
  - "signal_orchestrator_service.py consuming typed IntelligenceEvent via model_validate_json()"
  - "SSE route format-aware (comment added, no intelligence field access broken)"
  - "dashboard parseIntelligence() parsing p.event as JSON, accessing i3/i4/i5/smc/i6 tiers"
  - "8 new tests in test_signal_generator_service.py for typed deserialization"
  - "4 replacement tests in test_signal_orchestrator_helpers.py for _parse_intelligence_event"
affects:
  - 01-03
  - any future consumer of intelligence: Redis stream
  - dashboard frontend intelligence display

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_parse_intelligence_event(fields) pattern: reads b'event' field, model_validate_json(), returns None on failure"
    - "_build_features_from_event(event) pattern: explicit mapping from typed fields to legacy MARKET_CONTEXT_KEYS dict"
    - "Ack-and-skip on None event: malformed messages are acknowledged (not leaked) and silently skipped"

key-files:
  created:
    - tests/unit/service_tests/test_signal_generator_service.py
  modified:
    - services/signal_generator_service.py
    - services/signal_orchestrator_service.py
    - src/api/routes/sse.py
    - dashboard/src/hooks/use-market-stream.ts
    - tests/unit/service_tests/test_signal_orchestrator_helpers.py

key-decisions:
  - "Features dict constructed with legacy key names (trend_regime, volatility_regime, etc.) for signal_ledger market_context JSONB stability — sourced from typed event fields"
  - "smc_trend_direction (schema rename) maps to SmartMoneyData.trend_direction in dashboard — noted in both service and frontend comment"
  - "Module-level _logger/_parse_intelligence_event helpers (not class methods) — pure functions easier to test without class instantiation"
  - "asyncio.run() replaced with pytest.mark.asyncio in async test to avoid event loop contamination of test_signal_tracker_service"
  - "ai_narrative_service.py confirmed non-consumer — reads signals:SYMBOL:TF:aggregated, not intelligence:"

patterns-established:
  - "_parse_intelligence_event pattern: all intelligence consumers use this identical pattern — reads b'event', validates, returns typed event or None"
  - "_build_features_from_event pattern: bridges typed IntelligenceEvent to legacy features dict expected by MARKET_CONTEXT_KEYS and I7 plugin frames"

requirements-completed:
  - BUS-03

# Metrics
duration: 25min
completed: 2026-02-23
---

# Phase 1 Plan 02: Consumer Migration Summary

**All intelligence stream consumers migrated to IntelligenceEvent.model_validate_json() — parse_intelligence_message() deleted from both signal services, dashboard parseIntelligence() parsing nested JSON tiers**

## Performance

- **Duration:** 25 min
- **Started:** 2026-02-23T00:00:00Z
- **Completed:** 2026-02-23T00:25:00Z
- **Tasks:** 3
- **Files modified:** 5 (+ 1 created)

## Accomplishments
- `signal_generator_service.py` and `signal_orchestrator_service.py` both use `IntelligenceEvent.model_validate_json()` — `parse_intelligence_message()` deleted from both
- `dashboard/src/hooks/use-market-stream.ts` `parseIntelligence()` now parses `p.event` as JSON and accesses `i3`/`i4`/`i5`/`smc`/`i6` tier objects
- 12 new/updated tests added covering typed deserialization, None handling, and attribute routing
- Full test suite: 577 passing (9 net new tests over 568 baseline)
- `ai_narrative_service.py` confirmed as non-consumer (reads `signals:` stream, not `intelligence:`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Migrate signal_generator_service to typed IntelligenceEvent** - `7b2f40b` (feat)
2. **Task 2: Update SSE route and dashboard parseIntelligence** - `e0bcdc8` (feat)
3. **Task 3: Migrate signal_orchestrator_service to typed IntelligenceEvent** - `6e06134` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `services/signal_generator_service.py` - Replaced `parse_intelligence_message()` with `_parse_intelligence_event()` + `_build_features_from_event()`, updated `_process_single_message()` to use typed attributes
- `services/signal_orchestrator_service.py` - Same migration pattern as signal_generator_service; removed `_META_FIELDS` frozenset
- `src/api/routes/sse.py` - Added format comment near `intelligence:` stream relay noting `{"event": "<IntelligenceEvent JSON>"}` shape
- `dashboard/src/hooks/use-market-stream.ts` - `parseIntelligence()` now parses `p.event` as JSON and extracts `i3`/`i4`/`i5`/`smc`/`i6` tiers with null-safe optional chaining
- `tests/unit/service_tests/test_signal_generator_service.py` - Created: 8 tests covering `_parse_intelligence_event()`, `_build_features_from_event()`, and async `_process_single_message()` end-to-end
- `tests/unit/service_tests/test_signal_orchestrator_helpers.py` - Updated: replaced 3 old `parse_intelligence_message` tests with 4 `_parse_intelligence_event` tests (5 existing `build_ledger_entries` tests retained)

## Decisions Made

- **Legacy key names in features dict:** `MARKET_CONTEXT_KEYS` uses old flat-dict names (`volatility_regime`, `volatility_percentile`, `hmm_regime_state`). These keys are preserved in `_build_features_from_event()` output for signal_ledger `market_context` JSONB stability — only the values are sourced from typed fields (`event.i4.vol_regime`, `event.i4.vol_percentile`, `event.smc.hmm_regime`).

- **smc_trend_direction rename:** The schema renames `trend_direction` → `smc_trend_direction` in `SMCContext` to avoid collision with `I3Structure.trend_direction`. Dashboard maps `smc.smc_trend_direction` → `SmartMoneyData.trend_direction` with a comment noting the rename.

- **Module-level helpers (not class methods):** `_parse_intelligence_event()` and `_build_features_from_event()` are module-level pure functions in both services — same as Plan 01-01 pattern. Easier to test without class instantiation overhead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Fixed asyncio event loop contamination in test**

- **Found during:** Task 1 (test_signal_generator_service.py creation)
- **Issue:** Using `asyncio.run()` in a sync test function closed the event loop, causing `test_signal_tracker_service.py` tests to fail with `RuntimeError: There is no current event loop` when run in the full suite
- **Fix:** Changed `test_process_message_accesses_typed_attributes` from a sync function using `asyncio.run()` to an `async def` using `@pytest.mark.asyncio`
- **Files modified:** tests/unit/service_tests/test_signal_generator_service.py
- **Verification:** All 78 service tests pass in sequence; `test_signal_tracker_service.py` no longer fails
- **Committed in:** `7b2f40b` (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical test correctness)
**Impact on plan:** Required to prevent pre-existing fragile `asyncio.get_event_loop()` usage in test_signal_tracker_service from failing. No scope creep.

## Issues Encountered

- `ai_narrative_service.py` audit confirmed non-consumer: single `xreadgroup` call at line 402 reads from `signals:SYMBOL:TF:aggregated`, not `intelligence:`. No migration needed. Documented as "confirmed non-consumer".
- TypeScript build infrastructure error (missing `server-external-packages.jsonc`) is pre-existing and unrelated; `npx tsc --noEmit` confirms no new type errors in `use-market-stream.ts`.

## Next Phase Readiness

- All three consumer migration tasks complete
- `parse_intelligence_message()` absent from both signal services
- Plan 01-03 can proceed: delete `intelligence_processor_service.py`, audit remaining consumers, run full migration audit

## Self-Check: PASSED

All key files verified present:
- services/signal_generator_service.py - FOUND
- services/signal_orchestrator_service.py - FOUND
- src/api/routes/sse.py - FOUND
- dashboard/src/hooks/use-market-stream.ts - FOUND
- tests/unit/service_tests/test_signal_generator_service.py - FOUND
- .planning/phases/01-typed-event-schema/01-02-SUMMARY.md - FOUND

All task commits verified:
- 7b2f40b (Task 1: signal_generator_service migration) - FOUND
- e0bcdc8 (Task 2: SSE route + dashboard) - FOUND
- 6e06134 (Task 3: signal_orchestrator_service migration) - FOUND

Final verification: 577 tests passing, 0 regressions

---
*Phase: 01-typed-event-schema*
*Completed: 2026-02-23*
