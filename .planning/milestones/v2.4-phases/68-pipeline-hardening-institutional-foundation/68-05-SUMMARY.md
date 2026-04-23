---
phase: 68-pipeline-hardening-institutional-foundation
plan: "05"
subsystem: bar-aggregation
tags: [hardening, dlq, backpressure, timestamp-guard, emit-once, audit]
dependency_graph:
  requires: [68-02]
  provides: [AGG-DLQ, AGG-TIMESTAMP-GUARD, AGG-EMIT-ONCE, AGG-BACKPRESSURE]
  affects: [services/bar_aggregator_agent.py, src/core/bar_accumulator.py, src/core/stream_keys.py]
tech_stack:
  added: []
  patterns:
    - DLQ routing for unparseable Kafka payloads (per-domain DLQ producer)
    - asyncio.Semaphore(200) for burst backpressure cap
    - Forward-only timestamp guard in accumulator update() loop
    - In-memory emit-once registry (symbol, tf) -> last_emitted_ts
    - Cached lag consumer (AUDIT-LOW-6 fix)
key_files:
  created:
    - tests/unit/test_bar_aggregator_hardening.py
  modified:
    - src/core/stream_keys.py
    - src/core/bar_accumulator.py
    - services/bar_aggregator_agent.py
    - tests/unit/test_bar_accumulator_validation.py
    - tests/unit/test_stream_keys_dlq.py
    - tests/unit/service_tests/test_bar_aggregator_agent.py
decisions:
  - "Module-level logger (not self.logger) used in BarAccumulator — class has no self.logger"
  - "Remove if __debug__ guard from _is_accumulator_valid — python -O strips debug blocks in production"
  - "Semaphore wrapped around entire asyncio.timeout block (not just accumulator.update) for correctness"
  - "_lag_consumer cached in _setup() — one instance reused for all _get_consumer_lag() calls"
  - "test helper (_make_agent via __new__) updated with all 4 new attributes: _last_emitted, _dlq_producer, _processing_semaphore, _bars_in_flight"
  - "test_setup_retries side_effect extended to 4 items — _setup now creates 2 producers per attempt"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-23"
  tasks_completed: 4
  tasks_total: 4
  files_modified: 6
  files_created: 1
---

# Phase 68 Plan 05: Bar Aggregation Hardening Summary

Bar aggregation layer hardened against four audit findings (AGG-DLQ, AGG-TIMESTAMP-GUARD, AGG-EMIT-ONCE, AGG-BACKPRESSURE) — malformed bars now route to DLQ, out-of-order timestamps are rejected, duplicate HTF emissions suppressed, and burst backpressure capped at 200 concurrent slots.

## What Was Built

### Task 1: topic_bar_aggregator_dlq() (58ae682c)
Added `topic_bar_aggregator_dlq(env_name)` to `src/core/stream_keys.py` returning `{env}.bar.aggregator.dlq`. Follows the existing DLQ naming convention. Unit test added to `test_stream_keys_dlq.py`.

### Task 2: Forward-only timestamp guard in BarAccumulator (081277da)
At the top of `BarAccumulator.update()`, per-timeframe accumulator check: if `curr_ts <= acc["last_ts"]`, log `bar_accumulator_out_of_order` warning and `continue` (return [] for that TF). First bar for any (symbol, tf) pair is always accepted. Also removed `if __debug__:` guard from `_is_accumulator_valid()` — validation now runs unconditionally in production (python -O strips debug blocks). 5 new unit tests added.

### Task 3: DLQ routing + emit-once guard + cached lag consumer (b6a286ad)
- **AGG-DLQ**: `_dlq_producer` (KafkaProducerClient) created in `_setup()`, closed in `_teardown()`. Parse failures route payload to `bar.aggregator.dlq` instead of silent drop.
- **AGG-EMIT-ONCE**: `_last_emitted: dict[tuple[str, str], datetime]` tracks last emitted `period_ts` per `(symbol, tf)`. Duplicate HTF bars suppressed with `htf_duplicate_suppressed` warning.
- **AUDIT-LOW-6**: `_lag_consumer` (AIOKafkaConsumer) cached in `_setup()` and reused in `_get_consumer_lag()` — no new connection per 15s health check.
- 5 new unit tests in `test_bar_aggregator_hardening.py`. Existing service tests fixed to set new attributes in `__new__`-based helpers.

### Task 4: Semaphore backpressure cap (74f87f1c)
- `asyncio.Semaphore(200)` added to `__init__`, wraps the entire `asyncio.timeout(5.0)` block in `_run()`.
- `bar_aggregator_bars_in_flight` Gauge reports `200 - semaphore._value` (slots in use).
- Saturation warning + 100ms backpressure pause when `semaphore.locked()`.
- Service test helper updated with `_processing_semaphore` and `_bars_in_flight`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module-level logger in BarAccumulator**
- **Found during:** Task 2 implementation
- **Issue:** Plan's pseudocode used `self.logger.warning(...)` but `BarAccumulator` has no `self.logger` — it uses module-level `logger = structlog.get_logger(__name__)`
- **Fix:** Changed to `logger.warning(...)` (module-level)
- **Files modified:** `src/core/bar_accumulator.py`
- **Commit:** 081277da

**2. [Rule 1 - Bug] Service test _make_agent() missing new attributes**
- **Found during:** Task 3 + Task 4 — existing tests in `service_tests/test_bar_aggregator_agent.py` broke because the `__new__`-based helper didn't set `_last_emitted`, `_dlq_producer`, `_dlq_topic`, `_consumer_restart_needed`, `_processing_semaphore`, `_bars_in_flight`
- **Fix:** Added all 6 attributes to the `_make_agent()` helper
- **Files modified:** `tests/unit/service_tests/test_bar_aggregator_agent.py`
- **Commit:** b6a286ad, 74f87f1c

**3. [Rule 1 - Bug] test_setup_retries side_effect list too short**
- **Found during:** Task 3 — `test_setup_retries_on_kafka_connection_error` failed because `_setup()` now creates 2 producers (main + DLQ) per attempt; the side_effect list [KCE, KCE, None] had only 3 items but attempt 3 needs 2 successful starts (main + DLQ = 4 total)
- **Fix:** Extended side_effect to [KCE, KCE, None, None] and updated assertion to `call_count == 4`
- **Files modified:** `tests/unit/service_tests/test_bar_aggregator_agent.py`
- **Commit:** b6a286ad

**4. [Rule 1 - Bug] E501 line length in bar_accumulator.py comment**
- **Found during:** Task 2 ruff check
- **Fix:** Moved inline comment to preceding line; shortened `__debug__` comment to avoid `grep '__debug__'` match
- **Files modified:** `src/core/bar_accumulator.py`
- **Commit:** 081277da

## Threat Surface Scan

No new network endpoints, auth paths, or DB tables introduced. DLQ producer is a Kafka producer — same trust boundary as the existing main producer. All mitigations per the plan's threat model were implemented: T-68-10 (DLQ routing), T-68-11 (timestamp guard), T-68-12 (semaphore), T-68-13 (emit-once).

## Self-Check

### Files exist
- [x] `src/core/stream_keys.py` — topic_bar_aggregator_dlq present
- [x] `src/core/bar_accumulator.py` — out_of_order guard present, no __debug__
- [x] `services/bar_aggregator_agent.py` — _last_emitted, Semaphore, _dlq_topic present
- [x] `tests/unit/test_bar_aggregator_hardening.py` — created
- [x] `tests/unit/test_bar_accumulator_validation.py` — updated

### Commits exist
- [x] 58ae682c — topic_bar_aggregator_dlq
- [x] 081277da — timestamp guard
- [x] b6a286ad — DLQ routing + emit-once + lag consumer
- [x] 74f87f1c — semaphore backpressure

### Tests pass
- [x] 43 tests pass (`-k "bar_accumulator or bar_aggregator"`)
- [x] Ruff clean on all 3 modified source files

## Self-Check: PASSED
