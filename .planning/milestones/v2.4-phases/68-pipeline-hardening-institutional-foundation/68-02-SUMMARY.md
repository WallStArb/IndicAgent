---
phase: 68-pipeline-hardening-institutional-foundation
plan: 02
subsystem: infra
tags: [kafka, writer-agents, base-class, offset-commit, dlq, buffer-bounds]

# Dependency graph
requires: []
provides:
  - BaseWriterAgent ABC in src/core/agent/base_writer.py
  - All 5 writer agents inheriting BaseWriterAgent with manual offset commit
  - Bounded buffer with overflow metric and buffer depth gauge
  - DLQ routing for unparseable payloads
  - Final flush on teardown guarantee
affects: [68-04, signal-writer, feature-writer, bar-writer, lifecycle-writer, swarm-writer]

# Tech tracking
tech-stack:
  added: []
  patterns: [BaseWriterAgent consume-parse-buffer-flush-commit loop, module-level Prometheus metric cache]

key-files:
  created:
    - src/core/agent/base_writer.py
    - tests/unit/test_base_writer_agent.py
  modified:
    - services/signal_writer_agent.py
    - services/feature_writer_agent.py
    - services/bar_writer_agent.py
    - services/lifecycle_writer_agent.py
    - services/swarm_writer_agent.py
    - src/core/agent/__init__.py
    - tests/unit/service_tests/test_signal_writer_agent.py
    - tests/unit/service_tests/test_lifecycle_writer_agent.py
    - tests/unit/service_tests/test_bar_writer_agent.py
    - tests/unit/service_tests/test_feature_writer_agent.py
    - tests/unit/service_tests/test_swarm_writer_agent.py

key-decisions:
  - "BaseWriterAgent delegates _run() to subclasses (not a getmany-based loop) — existing writers use messages() async generator pattern"
  - "Module-level _gauges/_counters dicts for safe Prometheus metric registration in tests"
  - "Buffer overflow drops oldest entries (keeps newest) to preserve most recent data"
  - "Offset commit only after _flush_batch succeeds — buffer left intact on DB failure for retry"

patterns-established:
  - "BaseWriterAgent pattern: subclass implements _parse_payload, _flush_batch, _topic_name, _consumer_group; base class provides _buffer_rows, maybe_flush, _do_flush, _teardown"
  - "Writer _run() loop: consume via messages() -> _parse_payload -> _buffer_rows -> maybe_flush"
  - "enable_auto_commit=False on all writer consumers with manual commit after flush"

requirements-completed: [WRITER-BASE-CLASS, WRITER-OFFSET-COMMIT, WRITER-DLQ, WRITER-BUFFER-BOUND]

# Metrics
duration: 31min
completed: 2026-04-13
---

# Phase 68 Plan 02: BaseWriterAgent ABC + Writer Migration Summary

**BaseWriterAgent ABC with manual offset-commit, DLQ routing, bounded buffer, and all 5 writer agents migrated to inherit from it**

## Performance

- **Duration:** 31 min
- **Started:** 2026-04-13T03:36:23Z
- **Completed:** 2026-04-13T04:07:20Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments
- Created BaseWriterAgent ABC extracting ~200 lines of duplicated buffer/flush/overflow/teardown logic across all 5 writers
- All 5 writers now enforce manual offset commit only after successful _flush_batch (prevents data loss on crash)
- Bounded buffer (MAX_BUFFER_SIZE=10,000) with overflow metric on all writers
- Buffer depth gauge published every consume cycle
- DLQ routing when _parse_payload returns None (log-only if _dlq_topic returns None)
- Final flush on teardown guaranteed by BaseWriterAgent._teardown()
- 100 unit tests passing across all writer agents

## Task Commits

Each task was committed atomically:

1. **Task 1: Create BaseWriterAgent ABC** - `b81f76fd` (feat) — TDD: RED tests first, then GREEN implementation
2. **Task 2: Migrate all 5 writer agents** - `8a3f2376` (refactor) — 10 files, net -132 lines of code removed

## Files Created/Modified
- `src/core/agent/base_writer.py` - BaseWriterAgent ABC with buffer/flush/commit/overflow/teardown loop
- `src/core/agent/__init__.py` - Added BaseWriterAgent export
- `tests/unit/test_base_writer_agent.py` - 12 behavioral tests (8 test classes)
- `services/signal_writer_agent.py` - Migrated to BaseWriterAgent, enable_auto_commit=False
- `services/feature_writer_agent.py` - Migrated to BaseWriterAgent, enable_auto_commit=False
- `services/bar_writer_agent.py` - Migrated to BaseWriterAgent, enable_auto_commit=False
- `services/lifecycle_writer_agent.py` - Migrated to BaseWriterAgent, enable_auto_commit=False
- `services/swarm_writer_agent.py` - Migrated to BaseWriterAgent, enable_auto_commit=False
- `tests/unit/service_tests/test_signal_writer_agent.py` - Updated for new method signatures
- `tests/unit/service_tests/test_lifecycle_writer_agent.py` - Updated for new method signatures
- `tests/unit/service_tests/test_bar_writer_agent.py` - Updated for _parse_payload/_flush_batch
- `tests/unit/service_tests/test_feature_writer_agent.py` - Updated for _parse_payload/_do_flush
- `tests/unit/service_tests/test_swarm_writer_agent.py` - Updated for _flush_batch/_do_flush

## Decisions Made
- **BaseWriterAgent delegates _run() to subclasses:** The plan's action block showed a getmany()-based _run() loop, but all 5 existing writers use the messages() async generator pattern. Forcing getmany() would require rewriting every writer's consumption loop. Instead, BaseWriterAgent provides helper methods (_buffer_rows, maybe_flush, _do_flush) that subclasses call from their own _run() loops.
- **Module-level metric cache:** Used _gauges/_counters dicts with _get_or_create_gauge/_get_or_create_counter helpers to prevent Prometheus duplicate registration in tests. Matches the pattern from src/observability/metrics.py.
- **Buffer overflow drops oldest:** Keeps newest entries (self._buffer[-MAX_BUFFER_SIZE:]) so recent data is preserved during pressure.
- **FeatureWriterAgent keeps its own _shutdown() method:** Complex multi-task _run() with _process_loop + _periodic_flush_loop + _health_monitor_loop, plus roll/cross-asset routing. BaseWriterAgent._teardown() handles final flush, then FeatureWriterAgent._teardown() calls _shutdown() for consumer/DB cleanup.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adapted _run() design from getmany() to messages() pattern**
- **Found during:** Task 1 (Create BaseWriterAgent ABC)
- **Issue:** Plan specified getmany()-based _run() with JSON decoding in base class, but all 5 writers use messages() async generator which already decodes JSON. Forcing getmany() would break every writer.
- **Fix:** Made _run() remain abstract in BaseWriterAgent (inherited from BaseAgent). Instead, provided _buffer_rows(), maybe_flush(), _do_flush(), _teardown() as helper methods that subclasses call from their own _run() loops.
- **Files modified:** src/core/agent/base_writer.py
- **Verification:** All 100 tests pass, all 5 writers function identically

**2. [Rule 3 - Blocking] Prometheus duplicate registration in tests**
- **Found during:** Task 1 (test execution)
- **Issue:** Creating multiple StubWriterAgent instances in tests causes ValueError for duplicate Prometheus metrics
- **Fix:** Added module-level _gauges/_counters dicts with _get_or_create_gauge/_get_or_create_counter helpers (same pattern as src/observability/metrics.py counter/gauge helpers)
- **Files modified:** src/core/agent/base_writer.py
- **Verification:** All 12 tests pass including multiple instantiations

**3. [Rule 3 - Blocking] Updated 5 test files for new method signatures**
- **Found during:** Task 2 (migration verification)
- **Issue:** Existing tests call removed methods (_flush, _buffer_bar, _flush_buffer, _write_batch, _handle_message, _parse_intelligence_record) and import removed module-level constants (BATCH_SIZE, FLUSH_INTERVAL_SECS)
- **Fix:** Updated all 5 test files to use new method names (_do_flush, _flush_batch, _parse_payload) and class-level attribute access (SignalWriterAgent.BATCH_SIZE instead of module-level import)
- **Files modified:** tests/unit/service_tests/test_{signal,lifecycle,bar,feature,swarm}_writer_agent.py
- **Verification:** 100 tests passing

---

**Total deviations:** 3 auto-fixed (3 blocking)
**Impact on plan:** All auto-fixes necessary for correctness. Net result is cleaner (subclasses own their _run() loop) and avoids a breaking change to the consumption pattern. No scope creep.

## Issues Encountered
- Pre-existing E501 in bar_writer_agent.py SQL INSERT line (106 chars) — deferred per deviation scope boundary rule

## Self-Check: PASSED

All files verified present:
- src/core/agent/base_writer.py
- tests/unit/test_base_writer_agent.py
- services/signal_writer_agent.py
- services/feature_writer_agent.py
- services/bar_writer_agent.py
- services/lifecycle_writer_agent.py
- services/swarm_writer_agent.py
- .planning/phases/68-pipeline-hardening-institutional-foundation/68-02-SUMMARY.md

All commits verified:
- b81f76fd (Task 1: BaseWriterAgent ABC)
- 8a3f2376 (Task 2: Migrate all 5 writers)

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 5 writer agents now share BaseWriterAgent with consistent write-path reliability guarantees
- Future writers (e.g., for new persistence tables in Plan 68-04) can inherit BaseWriterAgent for free buffer/flush/commit/overflow handling
- 3 other writer agents (ContractMetadataWriter, FeatureSnapshotWriter, SignalMetricsWriter) still inherit BaseAgent directly — not in scope for this plan but candidates for future migration

---
*Phase: 68-pipeline-hardening-institutional-foundation*
*Completed: 2026-04-13*
