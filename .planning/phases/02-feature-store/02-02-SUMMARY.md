---
phase: 02-feature-store
plan: "02"
subsystem: feature-writer-service
tags: [tdd, consumer-group, batch-writer, timescaledb, redis-streams, prometheus]
dependency_graph:
  requires: [02-01]
  provides: [02-03, 02-04]
  affects: [intelligence_features table, intelligence: Redis streams]
tech_stack:
  added: []
  patterns:
    - consumer group fixed name (feature_writer:persist) for restart resume
    - module-level pure functions for testability without class instantiation
    - __new__-safe design: hasattr guards in _maybe_flush for mock-friendly testing
    - json.dumps() for asyncpg JSONB serialization (not dict auto-coercion)
    - BATCH_SIZE=50 || elapsed>=FLUSH_INTERVAL_SECS=5.0 dual-flush trigger
key_files:
  created:
    - services/feature_writer_service.py
    - config/feature_writer_service.json
    - tests/unit/service_tests/test_feature_writer_service.py
  modified: []
decisions:
  - "hasattr guards in _maybe_flush allow __new__-constructed service instances in unit tests without triggering AttributeError on uninitialized metrics fields"
  - "Consumer group name is fixed 'feature_writer:persist' — NOT timestamped — so service resumes from last acknowledged position on restart"
  - "bar and i1 use model_dump() without exclude_none; i3-i6 use exclude_none=True for storage compactness (strict models with many optional fields)"
metrics:
  duration: ~4min
  completed: "2026-02-23T19:10:55Z"
  tasks_completed: 2
  files_created: 3
  files_modified: 0
---

# Phase 2 Plan 02: Feature Writer Service — consumer group batch writer

Async consumer group service consuming `intelligence:SYMBOL:TF` Redis streams via fixed consumer group `feature_writer:persist` and batch-writing rows to the `intelligence_features` TimescaleDB hypertable using `DatabaseManager.execute_batch`.

## What Was Built

### services/feature_writer_service.py (471 lines)

Production service implementing:

- `CONSUMER_GROUP = "feature_writer:persist"` — fixed string (not timestamped) for restart-resume correctness
- `_parse_intelligence_event(fields)` — module-level pure function, identical pattern to `signal_generator_service.py`; reads `b"event"` key, calls `IntelligenceEvent.model_validate_json()`, returns `None` on any failure (ack-and-skip)
- `_event_to_insert_params(event)` — module-level pure function returning 13-element tuple; JSONB columns are `json.dumps()` strings (asyncpg requires strings, not dicts)
- `_INSERT_FEATURE_SQL` — 13-param INSERT with `ON CONFLICT (ts, symbol, tf) DO NOTHING`
- `FeatureWriterService._maybe_flush(force)` — flushes when `force=True` OR `elapsed >= FLUSH_INTERVAL_SECS=5.0`; no-op if buffer empty
- `FeatureWriterService._shutdown()` — sets `shutdown_requested=True`, calls `_maybe_flush(force=True)`, closes Redis + DB connections
- Prometheus metrics on port 9116 (`events_consumed_total`, `batch_writes_total`, buffer gauge, uptime gauge)

### config/feature_writer_service.json

Matches `market_analysis_service.json` symbols/timeframes; `metrics_port: 9116` (9115 is occupied by signal_tracker_service).

### tests/unit/service_tests/test_feature_writer_service.py (245 lines, 10 tests)

TDD test suite covering all specified behaviors:

| Test | Coverage |
|------|----------|
| `test_parse_valid_event_returns_intelligence_event` | Happy path parse |
| `test_parse_missing_event_field_returns_none` | Missing b'event' key |
| `test_parse_malformed_json_returns_none` | Bad JSON ack-and-skip |
| `test_event_to_insert_params_returns_13_tuple` | Tuple length |
| `test_event_to_insert_params_first_element_is_datetime` | ts column type |
| `test_event_to_insert_params_jsonb_columns_are_strings` | asyncpg serialization |
| `test_maybe_flush_force_calls_execute_batch` | Forced flush |
| `test_maybe_flush_time_based_calls_execute_batch` | Time-based flush |
| `test_maybe_flush_recent_events_no_call` | No premature flush |
| `test_graceful_shutdown_sets_flag_and_flushes` | Shutdown with flush |

## TDD Flow

**RED (Task 1, commit 25e4dbe):** Test file written with 10 tests; all failed with `ModuleNotFoundError: No module named 'services.feature_writer_service'`.

**GREEN (Task 2, commit 17c41bb):** Service implemented; initial run had 3 failures due to `AttributeError` on uninitialized metrics attributes when tests use `__new__` to bypass `__init__`. Fixed by adding `hasattr` guards in `_maybe_flush` and `_shutdown`. All 10 tests GREEN on second run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] hasattr guards for __new__-constructed test instances**
- **Found during:** Task 2 GREEN
- **Issue:** Tests use `FeatureWriterService.__new__(FeatureWriterService)` to bypass `__init__`, which means `batch_writes_total`, `error_count_total`, `events_buffered_gauge`, `_total_events`, `_total_batches`, `_error_count` are not set. `_maybe_flush` and `_shutdown` raised `AttributeError` on these attributes.
- **Fix:** Added `hasattr(self, ...)` guards before accessing metrics/counter attributes in `_maybe_flush` and used `getattr(..., 0)` default in `_shutdown` logger call.
- **Files modified:** `services/feature_writer_service.py`
- **Commit:** 17c41bb (included in GREEN commit)

## Verification Results

```
# All 10 feature writer tests pass
tests/unit/service_tests/test_feature_writer_service.py  10/10 PASSED

# Full unit suite
569 passed, 3 failed (pre-existing), 70 warnings

# Import and assertions
CONSUMER_GROUP == 'feature_writer:persist'  ✓
'$13::jsonb' in _INSERT_FEATURE_SQL         ✓
BATCH_SIZE == 50                            ✓
```

## Self-Check: PASSED

- `services/feature_writer_service.py` exists (471 lines, > min 200)
- `tests/unit/service_tests/test_feature_writer_service.py` exists (245 lines, > min 80)
- `config/feature_writer_service.json` exists
- Commit 25e4dbe: `test(02-02): add failing tests for feature_writer_service`
- Commit 17c41bb: `feat(02-02): implement feature_writer_service batch writer`
