---
phase: 04-query-api
plan: "03"
subsystem: api
tags: [fastapi, sse, intelligence-event, pydantic, pytest]

# Dependency graph
requires:
  - phase: 04-01
    provides: features router (GET /api/features/{symbol}/{timeframe}, GET /api/features/export)
  - phase: 04-02
    provides: signals router (GET /api/signals/{symbol})
provides:
  - features and signals routers wired into main.py — routes return 503 (db not ready), not 404
  - SSE _event_name_for_stream behavior locked by 9 unit tests
  - Confirmed SSE intelligence_data payload format: payload.event is a JSON string, not a dict
affects: [05-auth, 06-ml-scoring, dashboard-frontend]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TestClient(app, raise_server_exceptions=False) for verifying route registration without lifespan DB"
    - "SSE payload convention: {'event': '<IntelligenceEvent JSON>'} — dashboard calls JSON.parse(payload.event)"

key-files:
  created:
    - tests/unit/api/test_sse_intelligence.py
  modified:
    - src/api/main.py

key-decisions:
  - "Test code adapted from plan: IntelligenceEvent constructor requires full field set (bar, i1-i6 sub-models) — plan had simplified form that would fail; used _make_minimal_event() pattern from existing test_feature_writer_service.py"
  - "Pre-existing test failures (test_settings.py::test_get_point_value, test_ibkr_provider.py, test_market_analysis_service.py) are out-of-scope — deferred, not fixed"

patterns-established:
  - "_make_minimal_event() helper pattern for IntelligenceEvent construction in tests — builds full valid event with minimal field values"

requirements-completed: [API-03]

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 4 Plan 03: SSE Payload Lock + Router Registration Summary

**features and signals routers wired into main.py; SSE intelligence_data payload format locked by 9 tests verifying _event_name_for_stream routing and JSON string payload structure**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-24T11:38:40Z
- **Completed:** 2026-02-24T11:41:12Z
- **Tasks:** 2
- **Files modified:** 2 (main.py updated, test_sse_intelligence.py created)

## Accomplishments

- Registered features and signals routers in main.py — /api/features/{symbol}/{timeframe}, /api/features/export, and /api/signals/{symbol} are now live endpoints (return 503 not 404 when DB not initialized)
- Created 9 unit tests locking the SSE intelligence_data payload format — _event_name_for_stream routing verified for all 6 stream domains plus env-prefix handling
- Confirmed SSE payload convention: `{"event": "<IntelligenceEvent JSON string>"}` — dashboard correctly calls JSON.parse(payload.event) to deserialize

## Task Commits

Each task was committed atomically:

1. **Task 1: Register features and signals routers in main.py** - `fbf9cf4` (feat)
2. **Task 2: Add SSE intelligence payload tests to lock API-03 behavior** - `d10133b` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `/home/bg/dev/indicagent/src/api/main.py` - Added `features, signals` to route imports and two `app.include_router()` calls; ruff auto-fixed import sort order
- `/home/bg/dev/indicagent/tests/unit/api/test_sse_intelligence.py` - 9 tests: TestEventNameMapping (7) + TestSSEPayloadFormat (2)

## Decisions Made

- Test code in the plan used `IntelligenceEvent(symbol="ESH6", timeframe="1m", ts=...)` which would fail since the actual model uses `tf` (not `timeframe`) and requires `bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6` sub-models. Adapted using `_make_minimal_event()` helper pattern from existing `test_feature_writer_service.py`.
- Pre-existing test failures exist in out-of-scope files (`test_settings.py`, `test_ibkr_provider.py`, `test_market_analysis_service.py`, `test_historical_backfill.py`) — not caused by this plan's changes; deferred.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected IntelligenceEvent constructor in test fixtures**
- **Found during:** Task 2 (SSE intelligence payload tests)
- **Issue:** Plan's test code used `IntelligenceEvent(symbol="ESH6", timeframe="1m", ts=...)` with wrong field name (`timeframe` vs `tf`) and missing required sub-model fields (`bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6`). This would have caused ValidationError at test runtime.
- **Fix:** Replaced with `_make_minimal_event()` helper function using complete valid constructor (matching pattern in `test_feature_writer_service.py`)
- **Files modified:** tests/unit/api/test_sse_intelligence.py
- **Verification:** 9 tests pass
- **Committed in:** d10133b (Task 2 commit)

**2. [Rule 3 - Blocking] Fixed ruff lint errors in generated files**
- **Found during:** Task 2 verification (ruff check)
- **Issue:** 4 lint errors: unsorted imports in main.py and test file, unused `pytest` import, `timezone.utc` instead of `datetime.UTC`
- **Fix:** Ran `ruff check --fix` to auto-fix all 4 errors
- **Files modified:** src/api/main.py, tests/unit/api/test_sse_intelligence.py
- **Verification:** `ruff check` passes with 0 errors on all touched files
- **Committed in:** d10133b (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for test correctness and code quality. No scope creep.

## Issues Encountered

- Pre-existing test failures in unrelated modules (12 failures total across `test_settings.py`, `test_ibkr_provider.py`, `test_market_analysis_service.py`, `test_signal_generator_service.py`, `test_signal_orchestrator_helpers.py`, `test_historical_backfill.py`) — all existed before this plan. API-specific tests (`tests/unit/api/`) are clean: 26/26 pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 4 (Query API) is now complete — all 3 plans executed:
  - 04-01: GET /api/features/{symbol}/{timeframe} and GET /api/features/export
  - 04-02: GET /api/signals/{symbol} with optional intelligence_features LEFT JOIN
  - 04-03: Routers wired into main.py; SSE payload format locked
- Phase 5 (Auth) depends on Phase 4 API existing — ready to proceed
- 26 Phase 4 unit tests pass; all API routes live and returning correct status codes

---
*Phase: 04-query-api*
*Completed: 2026-02-24*
