---
phase: 27-signal-lifecycle-stream-events
plan: "03"
subsystem: api
tags: [sse, signal-filter, age-filter, snapshot, reconnect]
dependency_graph:
  requires: []
  provides: [SSE snapshot age filter for signal streams]
  affects: [src/api/routes/sse.py, tests/unit/api/test_sse_routes.py]
tech_stack:
  added: []
  patterns: [lru_cache on static stream name lookups, Redis entry ID timestamp parsing]
key_files:
  created:
    - tests/unit/api/test_sse_routes.py
  modified:
    - src/api/routes/sse.py
decisions:
  - "helpers (_TF_MINUTES, _signal_max_age_s, _signal_entry_stale) were already pre-implemented in sse.py; only tests and snapshot integration remained"
  - "tests placed in tests/unit/api/ (existing api test dir) not tests/unit/api_tests/ (plan path was wrong)"
  - "cursor always advances even for stale entries so SSE reconnect position is correct"
metrics:
  duration: "~3 minutes"
  completed: "2026-03-12"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 27 Plan 03: SSE Snapshot Age Filter Summary

SSE snapshot age filter preventing stale signal replay on reconnect — skips signal entries older than 2×TF using Redis entry ID timestamps.

## What Was Built

- `_TF_MINUTES` dict mapping all 6 timeframes to their minute values
- `_signal_max_age_s()` — `@lru_cache` helper computing 2×TF threshold in seconds; returns `None` for non-signal streams
- `_signal_entry_stale()` — parses Unix-ms from Redis entry ID, compares age against threshold; always `False` for non-signal streams
- Age filter integrated into `event_generator()` snapshot loop: stale signal entries are skipped before yielding SSE frames; cursor (`last_ids`) still advances for all entries regardless of staleness

## Test Coverage

20 new unit tests in `tests/unit/api/test_sse_routes.py`:
- All 6 TF values in `_TF_MINUTES`
- `_signal_max_age_s()` for every TF, non-signal streams, malformed names, unknown TF
- `_signal_entry_stale()` fresh/stale boundaries for 5m and 1h, bytes entry_id, malformed IDs, 1m boundary, non-signal streams

## Deviations from Plan

### Pre-existing implementation

- **Found during:** Task 1
- **Issue:** `_TF_MINUTES`, `_signal_max_age_s()`, and `_signal_entry_stale()` were already in `sse.py` when execution started — helpers from a previous session
- **Fix:** Proceeded directly to writing tests (Task 1) and integrating snapshot loop (Task 2)
- **Impact:** No code written for Task 1 helper functions; only the test file and snapshot integration were new

### Test file path correction

- **Found during:** Task 1
- **Issue:** Plan specified `tests/unit/api_tests/test_sse_routes.py` but correct directory is `tests/unit/api/`
- **Fix:** Created `tests/unit/api/test_sse_routes.py` matching the established project convention
- **Impact:** None — same tests, correct location

## Self-Check

- [x] `tests/unit/api/test_sse_routes.py` — 120 lines, 20 tests
- [x] `src/api/routes/sse.py` — `_signal_entry_stale()` called in snapshot loop
- [x] Commit `70932c8` — Task 1: helpers + tests
- [x] Commit `1526981` — Task 2: snapshot loop integration
- [x] 1523 unit tests passing (20 new)

## Self-Check: PASSED
