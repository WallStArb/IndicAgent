---
phase: 16-llm-intelligence-layer
plan: "04"
subsystem: services
tags: [llm, redis, signal-lifecycle, outcome-emission, asyncio, tdd]

# Dependency graph
requires:
  - phase: 16-01
    provides: "llm_outcomes_stream key helper in src/core/stream_keys.py"
  - phase: 16-02
    provides: "LLMWriterService consuming llm_outcomes:stream; outcome back-fill to llm_calls DB rows"
provides:
  - "services/signal_lifecycle_service.py — both exit paths emit to llm_outcomes:stream via asyncio.create_task"
  - "_build_outcome_payload: pure function building flat dict[str,str] for Redis xadd"
affects: [16-05-deployment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Outcome emission before DB update: xadd fires via create_task BEFORE update_signal_status — outcome captured even if DB write fails"
    - "MAE/MFE capture before memory cleanup: emit uses self._mae.get(sid, current_mae) BEFORE self._mae.pop() — values guaranteed available"
    - "Symmetric exit paths: both shadow (regime_suppressed) and normal (active) exits use identical _build_outcome_payload signature"

key-files:
  created: []
  modified:
    - services/signal_lifecycle_service.py
    - tests/unit/service_tests/test_signal_lifecycle_service.py

key-decisions:
  - "Emit BEFORE update_signal_status on both paths — outcome captured even if DB write fails (fail-safe ordering)"
  - "Emit BEFORE memory cleanup (self._mae.pop) — MAE/MFE values are still available at emit time"
  - "maxlen=200 approximate trim on both emits — matches llm_outcomes retention policy from 16-01"

requirements-completed: [LLM-03]

# Metrics
duration: 2min
completed: 2026-03-06
---

# Phase 16 Plan 04: Signal Lifecycle Outcome Emission Summary

**signal_lifecycle_service emits to llm_outcomes:stream via fire-and-forget asyncio.create_task on both signal exit paths (shadow regime_suppressed and normal active→exit) using _build_outcome_payload pure helper**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-06T00:10:03Z
- **Completed:** 2026-03-06T00:11:56Z
- **Tasks:** 3 (task 3 was verification-only, no commit)
- **Files modified:** 2

## Accomplishments

- `_build_outcome_payload` — module-level pure function producing `dict[str, str]` with 7 fields: signal_id, outcome, pnl_r, mae, mfe, bars_in_trade, outcome_at; None numerics → ""; 0.0 → "0.0"
- Shadow exit path (regime_suppressed): fire-and-forget `xadd` to `llm_outcomes:stream` added BEFORE `update_signal_status` and BEFORE `self._mae.pop()` memory cleanup
- Normal Active→Exit path: fire-and-forget `xadd` added BEFORE memory cleanup and BEFORE shared `update_signal_status` call
- Import `llm_outcomes_stream as sk_llm_outcomes_stream` added to service imports
- 5 new `TestBuildOutcomePayload` unit tests GREEN (TDD: RED → GREEN cycle completed)
- Full unit suite: **1161 passing**, 0 regressions

## Task Commits

1. **Task 1: _build_outcome_payload helper + unit tests** - `5964457` (feat, TDD)
2. **Task 2: Wire llm_outcomes:stream emission on both exit paths** - `6260e7a` (feat)
3. **Task 3: Full unit suite regression** — verification-only, no commit

## Files Created/Modified

- `services/signal_lifecycle_service.py` — added `_build_outcome_payload` module-level function; import `sk_llm_outcomes_stream`; two `asyncio.create_task(xadd(...))` emits at both exit paths
- `tests/unit/service_tests/test_signal_lifecycle_service.py` — 5 new `TestBuildOutcomePayload` tests appended; no existing tests modified

## Decisions Made

- Emit BEFORE `update_signal_status` on both exit paths — if DB write fails, outcome record is already in-flight to the stream; data capture has priority over DB consistency
- Emit BEFORE `self._mae.pop(sid, None)` memory cleanup — MAE/MFE values are available at emit time; reversed order would produce empty/zero values
- `maxlen=200 approximate=True` consistent with llm_outcomes retention policy set in 16-01

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- LLM-03 complete: signal_lifecycle_service now feeds outcome data to llm_outcomes:stream
- Combined with 16-02 (LLMWriterService consuming llm_outcomes:stream), the full feedback loop is wired: LLM call logged → signal exits → outcome back-fills llm_calls rows
- Phase 16 Plan 05 (deployment/systemd) is the final step

## Self-Check: PASSED

- `services/signal_lifecycle_service.py` — FOUND
- `tests/unit/service_tests/test_signal_lifecycle_service.py` — FOUND
- `.planning/phases/16-llm-intelligence-layer/16-04-SUMMARY.md` — FOUND
- Commit `5964457` (Task 1) — FOUND
- Commit `6260e7a` (Task 2) — FOUND
- 1161 unit tests passing, 0 ruff errors on service file

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-06*
