---
phase: 16-llm-intelligence-layer
plan: "01"
subsystem: database
tags: [timescaledb, hypertable, stream-keys, tdd, llm, audit-log, scoring]

# Dependency graph
requires:
  - phase: 15-signal-ledger
    provides: "signal_ledger table with signal_id FK used by llm_calls"
provides:
  - "llm_calls TimescaleDB hypertable — full LLM audit log partitioned by called_at"
  - "llm_model_scores aggregate table — model performance with Renaissance significance gate"
  - "stream_keys.py: llm_calls_stream(), llm_outcomes_stream(), llm_scores_cache() helpers"
  - "TDD RED test suite (7 failing) — contracts defined for llm_writer_service implementation"
affects: [16-02-llm-writer-service, 16-03-ai-narrative-instrumentation, 16-04-lifecycle-emission, 16-05-deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TimescaleDB hypertable: called_at partitioning with if_not_exists guard"
    - "Outcome back-fill pattern: NULL columns at insert, written when lifecycle exit event arrives"
    - "Renaissance significance gate: n_outcomes >= 30 AND p_value < 0.05 for is_significant=TRUE"
    - "TDD RED: stream key tests PASS (contract locked), service function tests FAIL (module not created)"

key-files:
  created:
    - production/migrations/019_llm_intelligence_layer.sql
    - tests/unit/service_tests/test_llm_writer_service.py
  modified:
    - src/core/stream_keys.py

key-decisions:
  - "llm_calls partitioned by called_at (not signal_id) — primary access pattern is time-range queries for model scoring"
  - "Outcome columns NULL at insert, back-filled by llm_writer_service on llm_outcomes:stream event"
  - "is_significant gate: n_outcomes >= 30 AND p_value < 0.05 — no model routing without proof"
  - "Stream keys: {env}:llm_calls:stream maxlen=500, {env}:llm_outcomes:stream maxlen=200"
  - "llm_scores_cache key: {env}:llm_scores:{call_type}:{regime} — HSET with model as field"
  - "TDD RED confirmed: 5 stream key tests PASS (locked), 7 service tests FAIL (ModuleNotFoundError)"

patterns-established:
  - "Back-fill pattern: insert with NULL outcome columns, back-fill when lifecycle exit event arrives on llm_outcomes:stream"
  - "Score aggregate refresh: llm_model_scores updated after each outcome back-fill batch, not in real-time"

requirements-completed: [LLM-01]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 16 Plan 01: LLM Intelligence Layer Schema Foundation Summary

**TimescaleDB llm_calls hypertable + llm_model_scores table with Renaissance significance gate (n>=30, p<0.05), stream key helpers locked, and 7 TDD RED tests defining llm_writer_service contracts**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-05T19:32:58Z
- **Completed:** 2026-03-05T19:34:50Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Migration 019 creates `llm_calls` as a TimescaleDB hypertable partitioned by `called_at` — full audit log for every LLM call with outcome back-fill columns
- `llm_model_scores` aggregate table with PK `(model, regime, setup_type, call_type)` and `is_significant` gate requiring n_outcomes >= 30 AND p_value < 0.05
- Three new stream key helpers in `src/core/stream_keys.py` (`llm_calls_stream`, `llm_outcomes_stream`, `llm_scores_cache`) with expanded `get_stream_maxlen` Literal
- TDD RED confirmed: 5 stream key tests PASS (contracts locked), 7 service tests FAIL with `ModuleNotFoundError` — implementation deferred to Plan 16-02

## Task Commits

Each task was committed atomically:

1. **Task 1: DB migration 019_llm_intelligence_layer.sql** - `199c902` (feat)
2. **Task 2: Stream key helpers + TDD RED tests** - `941620c` (test)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `production/migrations/019_llm_intelligence_layer.sql` — llm_calls hypertable, llm_model_scores table, 3 indexes, COMMENT ON for key columns
- `src/core/stream_keys.py` — added llm_calls_stream(), llm_outcomes_stream(), llm_scores_cache(); extended get_stream_maxlen Literal with llm_calls=500, llm_outcomes=200
- `tests/unit/service_tests/test_llm_writer_service.py` — 12 tests total: 5 PASS (stream key contracts), 7 FAIL RED (llm_writer_service not yet created)

## Decisions Made

- `llm_calls` partitioned by `called_at` rather than `signal_id` — the primary access pattern is time-range queries when computing model scores, not per-signal lookup
- Outcome columns (`pnl_r`, `mae`, `mfe`, `win`, `outcome_at`) are NULL at insert and back-filled later — this avoids blocking the LLM call path on lifecycle resolution
- `is_significant` gate is `n_outcomes >= 30 AND p_value < 0.05` — encoding the Renaissance principle that no model earns trust before statistically significant proof
- Stream key maxlens: `llm_calls`=500 (higher volume, one per narrative call), `llm_outcomes`=200 (one per signal exit)
- `llm_scores_cache` key format: `{env}:llm_scores:{call_type}:{regime}` with model name as HSET field — enables per-model score lookup without full table scan

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Migration 019 must be applied to the TimescaleDB container before Plan 16-02 services are started:

```bash
docker exec timescaledb psql -U postgres -d indicagent -f /path/to/019_llm_intelligence_layer.sql
```

Or via the production migration runner if configured.

## Next Phase Readiness

- Schema contracts locked — Plans 16-02 through 16-05 can proceed
- Stream key helpers available for import by all LLM layer services
- 7 failing tests define exact function signatures expected in `services/llm_writer_service.py` (Plan 16-02 GREEN phase)
- Migration 019 ready for application — must run before `llm_writer_service` starts

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-05*
