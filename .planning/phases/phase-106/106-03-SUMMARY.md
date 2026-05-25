---
phase: 106-foundation-hardening
plan: 03
subsystem: infra
tags: [asyncpg, kafka, BaseAgent, BaseWriterAgent, retry, JSONB, connection-pool, teardown]

requires:
  - phase: 104-storage-architecture-redesign
    provides: database_manager.create_pool wrapper with JSONB codec registration

provides:
  - bar_aggregator uses BaseAgent._setup_with_retry with SETUP_RETRY_ATTEMPTS=4, SETUP_RETRY_BACKOFF_S=2.0
  - swarm_ledger_writer, bar_replay_provider, signal_replay_auditor create pools via database_manager wrapper
  - BaseWriterAgent._teardown auto-closes _consumer/_pool/_db behind getattr guards

affects:
  - any phase adding new BaseWriterAgent subclasses (teardown guards apply automatically)
  - any phase adding services that create asyncpg pools (should use database_manager.create_pool)

tech-stack:
  added: []
  patterns:
    - "Single-attempt _setup() body + class-attr-configured retry envelope via BaseAgent._setup_with_retry"
    - "create_db_pool alias for database_manager.create_pool with required pool_name kwarg"
    - "getattr(self, attr, None) guard pattern for safe auto-close in base class teardown"

key-files:
  created: []
  modified:
    - services/bar_aggregator_agent.py
    - services/swarm_ledger_writer_agent.py
    - services/bar_replay_provider_agent.py
    - services/signal_replay_auditor_agent.py
    - src/core/agent/base_writer.py
    - tests/unit/services/test_bar_aggregator_agent.py
    - tests/unit/core/test_base_writer_agent.py

key-decisions:
  - "Keep asyncpg import in all three services - still needed for type hints (asyncpg.Pool, asyncpg.Record)"
  - "Update bar_aggregator tests to test the new single-attempt contract; retry behavior is at BaseAgent level"
  - "BaseWriterAgent._teardown closes _pool and _db even though base class doesn't declare them - hasattr guard makes it safe for all subclasses"

patterns-established:
  - "SETUP_RETRY_ATTEMPTS/SETUP_RETRY_BACKOFF_S class attrs configure BaseAgent retry without subclassing _setup_with_retry"
  - "All asyncpg pool creation via database_manager.create_pool with unique pool_name per service"

duration: 15min
completed: 2026-05-25
---

# Phase 106 Plan 03: Infrastructure Code Reuse Summary

**Bar aggregator retry delegated to BaseAgent, three JSONB-bypass pools switched to database_manager.create_pool, and BaseWriterAgent._teardown hardened with auto-close guards for consumer/pool/db**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-25T00:50:00Z
- **Completed:** 2026-05-25T01:00:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Removed 40-line hand-rolled retry loop from bar_aggregator_agent._setup(); SETUP_RETRY_ATTEMPTS=4 / SETUP_RETRY_BACKOFF_S=2.0 class attrs preserve 4-attempt/2s-base behavior via BaseAgent._setup_with_retry()
- Three services (swarm_ledger_writer, bar_replay_provider, signal_replay_auditor) now create asyncpg pools through database_manager.create_pool, gaining JSONB codec registration (json/jsonb returns dict, not string) and pool size gauge instrumentation
- BaseWriterAgent._teardown now auto-closes _consumer/.stop(), _pool/.close(), and _db/.close() behind getattr guards so writer subclasses no longer leak connections on shutdown even if they override _teardown without calling super()

## Task Commits

1. **Task 1: Migrate bar_aggregator manual retry loop** - `1db3a1af` (refactor)
2. **Task 2: Switch 3 services to database_manager.create_pool** - `f3934733` (fix)
3. **Task 3: Add hasattr auto-close guards to BaseWriterAgent._teardown** - `97025743` (fix)

## Files Created/Modified

- `services/bar_aggregator_agent.py` - Added SETUP_RETRY_ATTEMPTS=4/SETUP_RETRY_BACKOFF_S=2.0; replaced manual retry loop with single-attempt body
- `services/swarm_ledger_writer_agent.py` - Switched to create_db_pool(pool_name="swarm_ledger_writer")
- `services/bar_replay_provider_agent.py` - Switched to create_db_pool(pool_name="bar_replay_provider")
- `services/signal_replay_auditor_agent.py` - Switched to create_db_pool(pool_name="signal_replay_auditor")
- `src/core/agent/base_writer.py` - Added auto-close guards to _teardown for _consumer, _pool, _db
- `tests/unit/services/test_bar_aggregator_agent.py` - Updated retry tests for single-attempt contract
- `tests/unit/core/test_base_writer_agent.py` - Added 5 teardown auto-close guard tests

## Decisions Made

- Kept `import asyncpg` in all three services - still needed for type hints (asyncpg.Pool, asyncpg.Record) even though create_pool call moved to database_manager wrapper
- Updated bar_aggregator unit tests to test the new contract (class attrs + single-attempt propagation) rather than the old loop behavior; BaseAgent-level retry tests already cover the retry envelope
- BaseWriterAgent._teardown guards _pool and _db with getattr even though the base class doesn't declare those attrs - the hasattr safety makes it applicable to any subclass automatically

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test assertions for bar_aggregator retry migration**
- **Found during:** Task 1 (Migrate bar_aggregator manual retry loop)
- **Issue:** Two existing tests (`test_setup_retries_on_kafka_connection_error`, `test_setup_raises_after_max_retries`) tested the multi-attempt loop behavior directly on `_setup()`. After the loop was removed, those tests failed since `_setup()` is now single-attempt only.
- **Fix:** Replaced the two old tests with three new tests: `test_setup_retry_class_attributes` (verifies SETUP_RETRY_ATTEMPTS=4, SETUP_RETRY_BACKOFF_S=2.0), `test_setup_single_attempt_success` (verifies one producer.start call), `test_setup_propagates_exception` (verifies exception propagates for BaseAgent to retry). Retry envelope behavior is already covered by test_base_agent.py.
- **Files modified:** `tests/unit/services/test_bar_aggregator_agent.py`
- **Committed in:** `1db3a1af` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test update required by production code change)
**Impact on plan:** Necessary test update; no scope creep. The test behavior change matches the production code contract change.

## Issues Encountered

- Worktree `.venv` symlink required: the pre-commit hook looks for `REPO_ROOT/.venv/bin/ruff` but the worktree's REPO_ROOT doesn't have a `.venv`. Created `ln -s /home/bg/dev/indicagent/.venv .venv` in the worktree to resolve.
- Two pre-existing test failures in `test_base_writer_agent.py` (TestOffsetCommit::test_no_commit_on_flush_failure, TestFlushLatencyMetrics::test_flush_errors_counter_increments_on_failure) - confirmed pre-existing before this plan's changes; out of scope.

## Next Phase Readiness

- JSONB codec coverage now complete for swarm_ledger_writer, bar_replay_provider, signal_replay_auditor
- Pool gauges available under pool_name labels: swarm_ledger_writer, bar_replay_provider, signal_replay_auditor
- BaseWriterAgent teardown hardening applies to all existing and future writer subclasses without further action
- Ready for Phase 106-04 (next plan)

---
*Phase: 106-foundation-hardening*
*Completed: 2026-05-25*
