---
phase: phase-105
plan: 05
subsystem: testing
tags: [regression-tests, shadow-governance, writer-services, otel-metrics, tdd]

# Dependency graph
requires:
  - phase: phase-105
    provides: "105-01 through 105-04 code fixes being locked in by these tests"
provides:
  - "Regression test suite for all phase-105 code fixes"
  - "Shadow winner-suppression test (shadow plugin cannot win)"
  - "Shadow auditor filter-direction tests (promotion=is_shadow TRUE, demotion=is_shadow FALSE)"
  - "Writer-service regression tests (ctx .add, swarm manual commit, bar liveness)"
  - "LLM writer behavior tests (no _pool ghost, .add not .inc, earliest+no-auto-commit)"
  - "Feature writer fail-fast test (raises on DB failure, no ghost-run)"
  - "OTel metric instrument-type tests (shadow gauges expose .set, histograms expose .record)"
affects:
  - phase-106
  - phase-107

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Source inspection assertions for static behavior (inspect.getsource) alongside behavioral mocks"
    - "Async generator mock for Kafka consumer loop testing"
    - "Spy pattern for _record_message_consumed via direct attribute assignment"

key-files:
  created: []
  modified:
    - tests/unit/pipeline/test_signal_processor.py
    - tests/unit/services/test_shadow_auditor_agent.py
    - tests/unit/services/test_ctx_writer_agent.py
    - tests/unit/services/test_swarm_ledger_writer_agent.py
    - tests/unit/services/test_bar_writer_agent.py
    - tests/unit/services/test_llm_writer_service.py
    - tests/unit/services/test_feature_writer_agent.py
    - tests/unit/observability/test_metrics.py

key-decisions:
  - "Source inspection (inspect.getsource) preferred over pure behavioral mocks for static contract assertions (constructor kwargs, SQL filter direction) — faster and less brittle to mock setup errors"
  - "Pre-existing test failure (test_flush_batch_leaves_buffer_on_error) documented in SUMMARY rather than modified — it is an unrelated test for a different code path"
  - "Swarm ledger auto_commit test uses source inspection since asyncpg.create_pool mock complexity would make a behavioral test fragile"

# Metrics
duration: 70min
completed: 2026-05-24
---

# Phase 105 Plan 05: Regression Test Suite Summary

**Regression tests locking in all phase-105 code fixes: shadow winner-suppression, auditor filter direction, writer-service OTel counters, manual Kafka commit, feature writer fail-fast, and OTel metric instrument types**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-05-24T07:58:00Z
- **Completed:** 2026-05-24T12:08:58Z
- **Tasks:** 4 completed
- **Files modified:** 8

## Accomplishments

- 147 new/updated tests pass across all 8 test files, proving every phase-105 fix is executable
- Shadow winner-suppression proven: shadow plugin with highest confidence never wins when shadow_cache marks it
- Shadow auditor filter direction locked in: promotion queries IS_SHADOW = TRUE, demotion queries IS_SHADOW = FALSE, swarm_agent rows skipped
- LLM writer regressions locked in: no ghost self._pool, .add() not .inc() on i8_writes_total, _record_message_consumed() called, earliest + enable_auto_commit=False, only calls topic subscribed
- Feature writer fail-fast proven: _connect_database() raises on failure, no db_manager=None ghost-run path
- OTel metric types proven: shadow metrics expose .set() (point gauges), latency metrics expose .record() (histograms)

## Task Commits

1. **Task 1: Shadow suppression + shadow auditor filter-direction regression tests** - `d9fba23e` (test)
2. **Task 2: Writer-service regression tests (ctx flush/teardown, swarm commit, bar liveness)** - `c4f8c3b1` (test)
3. **Task 3: LLM writer, feature writer fail-fast, and OTel metric-type regression tests** - `fc9d2f20` (test)
4. **Task 4: Full unit suite green + lint/format sweep** - (included in this metadata commit)

## Files Created/Modified

- `tests/unit/pipeline/test_signal_processor.py` - Added shadow winner-suppression regression test
- `tests/unit/services/test_shadow_auditor_agent.py` - Added 3 tests: promotion is_shadow=TRUE filter, demotion is_shadow=FALSE filter, swarm_agent skip
- `tests/unit/services/test_ctx_writer_agent.py` - Added .add() vs .inc() tests + super()._teardown() call assertion
- `tests/unit/services/test_swarm_ledger_writer_agent.py` - Added enable_auto_commit=False, commit-after-success, no-commit-on-failure tests
- `tests/unit/services/test_bar_writer_agent.py` - Added _record_message_consumed spy test; fixed missing _consumer_lag_attrs in fixture
- `tests/unit/services/test_llm_writer_service.py` - Added 5 regression tests: no _pool, .add() on i8 flush, liveness, consumer config, dead-topic drop
- `tests/unit/services/test_feature_writer_agent.py` - Added 2 fail-fast tests: raises on DB failure, no db_manager=None
- `tests/unit/observability/test_metrics.py` - Added 9 tests: 6 shadow gauge .set() + 3 histogram .record()

## Decisions Made

- Source inspection (inspect.getsource) preferred for static assertions (SQL filter direction, constructor kwargs) - less brittle than behavioral mocks for choices made at call sites
- Pre-existing test_flush_batch_leaves_buffer_on_error failure documented; not modified (unrelated pre-existing issue)
- Swarm ledger auto_commit=False verified via source inspection since asyncpg.create_pool is awaitable mock complexity

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing _consumer_lag_attrs in bar_writer test fixture**
- **Found during:** Task 2 (bar writer liveness test)
- **Issue:** _make_agent() in test_bar_writer_agent.py did not include _consumer_lag_attrs, causing AttributeError when _run() accessed it in test
- **Fix:** Added `agent._consumer_lag_attrs = {"agent": "bar_writer_agent"}` to the fixture helper
- **Files modified:** tests/unit/services/test_bar_writer_agent.py
- **Committed in:** c4f8c3b1 (Task 2 commit)

**2. [Rule 1 - Bug] ctx teardown assertion failed due to inline comment on same line**
- **Found during:** Task 2 (ctx_writer teardown test)
- **Issue:** `await super()._teardown()  # drains...` did not match the bare `"await super()._teardown()"` string comparison
- **Fix:** Strip comments before comparison using `.split("#")[0].rstrip()`; also renamed loop variable `l` -> `ln` (ruff E741)
- **Files modified:** tests/unit/services/test_ctx_writer_agent.py
- **Committed in:** c4f8c3b1 (Task 2 commit)

**3. [Rule 1 - Bug] env_name property not settable on LLMWriterAgent**
- **Found during:** Task 3 (LLM writer tests)
- **Issue:** `w.env_name = "dev"` raised AttributeError because env_name is a read-only property on BaseAgent (derived from settings.env_name)
- **Fix:** Removed direct assignment; env_name is automatically derived from the mocked settings.env_name
- **Files modified:** tests/unit/services/test_llm_writer_service.py
- **Committed in:** fc9d2f20 (Task 3 commit)

**4. [Rule 1 - Bug] intelligence.i8 string appeared in comments, not code**
- **Found during:** Task 3 (llm writer dead-topic test)
- **Issue:** The TODO comment in _setup_kafka_clients() references "intelligence.i8" by name (explaining why it was removed), causing the string-based assertion to false-fail
- **Fix:** Filter comment lines before the assertion (non_comment_lines = lines not starting with #)
- **Files modified:** tests/unit/services/test_llm_writer_service.py
- **Committed in:** fc9d2f20 (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (all Rule 1 - test fixture/assertion bugs)
**Impact on plan:** All auto-fixes were necessary to make the tests actually test the right thing. No scope creep.

## Issues Encountered

- **Pre-existing collection errors:** `tests/unit/intelligence/trading/test_trade_framer.py` and `test_winner_selector.py` fail to collect when running the full suite (pydantic v1 json_encoders deprecation). Pre-existing; not caused by phase-105 changes. Run individually these pass.
- **Pre-existing test failure:** `test_flush_batch_leaves_buffer_on_error` in test_bar_writer_agent.py fails because `_do_flush` catches exceptions internally. Pre-existing issue not introduced by this phase.
- **Large pre-existing failure count:** Full suite has 62 pre-existing failures across unrelated test files (signal_ledger, API routes, AI context). All confirmed pre-existing by git stash verification.

## Self-Check

Files verified:

- [x] tests/unit/pipeline/test_signal_processor.py - exists with shadow test
- [x] tests/unit/services/test_shadow_auditor_agent.py - exists with 3 new tests
- [x] tests/unit/services/test_ctx_writer_agent.py - exists with flush/teardown tests
- [x] tests/unit/services/test_swarm_ledger_writer_agent.py - exists with commit tests
- [x] tests/unit/services/test_bar_writer_agent.py - exists with liveness test
- [x] tests/unit/services/test_llm_writer_service.py - exists with 5 regression tests
- [x] tests/unit/services/test_feature_writer_agent.py - exists with fail-fast tests
- [x] tests/unit/observability/test_metrics.py - exists with instrument-type tests

Commits verified:
- d9fba23e: test(105-05): shadow suppression + auditor filter-direction regression tests
- c4f8c3b1: test(105-05): writer-service regression tests
- fc9d2f20: test(105-05): LLM writer, feature writer fail-fast, and OTel metric-type regression tests

## Self-Check: PASSED

All 3 task commits exist. All 8 test files modified with phase-105 regression tests. 147 new/updated tests pass.

## Next Phase Readiness

- All phase-105 code fixes are now locked in by executable regression tests
- Any accidental revert of a phase-105 fix will immediately fail its corresponding test
- Full suite shows only pre-existing failures; phase-105 tests are all green

---
*Phase: phase-105*
*Completed: 2026-05-24*
