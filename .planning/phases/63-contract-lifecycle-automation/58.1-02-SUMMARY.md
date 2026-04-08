---
phase: 58.1-contract-lifecycle-automation
plan: "02"
subsystem: infra
tags: [asyncpg, kafka, prometheus, systemd, futures, contract-lifecycle]

# Dependency graph
requires:
  - phase: 58.1-01
    provides: topic_roll_events, RollEvent schema, market_events.py foundation

provides:
  - ContractMetadataWriterAgent (services/contract_metadata_writer_agent.py)
  - indicagent-contract-metadata-writer.service systemd unit
  - topic_contract_updates() and topic_roll_dlq() stream key functions
  - ContractUpdateEvent schema in market_events.py
  - 11 unit tests covering all error paths

affects:
  - 58.1-03 (BarAuditorAgent consumes market.events.contract_update)
  - 58.1-04 (RollComputeAgent graduation — ContractMetadataWriterAgent must be live first)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "config-before-super pattern: Settings init before super().__init__() in BaseAgent subclass"
    - "asynccontextmanager for mocking asyncpg conn.acquire() in unit tests"
    - "Module-level prometheus metrics to prevent duplicate registration across test runs"

key-files:
  created:
    - services/contract_metadata_writer_agent.py
    - services/indicagent-contract-metadata-writer.service
    - tests/unit/test_contract_metadata_writer_agent.py
  modified:
    - src/core/stream_keys.py (added topic_contract_updates, topic_roll_dlq)
    - src/core/schemas/market_events.py (added ContractUpdateEvent)

key-decisions:
  - "topic_contract_updates and topic_roll_dlq added to stream_keys.py as plan 01 dependencies not yet in worktree (Rule 3 blocking fix)"
  - "ContractUpdateEvent added to market_events.py for same reason"
  - "asynccontextmanager used in test fixtures for conn.acquire() — avoids AsyncMock __aenter__/__aexit__ dunder lookup issues"
  - "DRY_RUN fetches old_row from DB before skipping write — ensures exchange copy logic is validated even in dry-run mode"
  - "IBKR_RESTART_REQUIRED warning key emitted on every successful promotion for operator alerting"

patterns-established:
  - "WriterAgent pattern: asyncpg.create_pool in _setup, acquire() context manager for each operation"
  - "__new__ bypass pattern for unit tests: manually set all __init__ attributes on agent instance"
  - "DLQ routing: ValidationError, empty fields, unknown old_contract — all routed to market.events.roll.dlq"

requirements-completed:
  - CLA-02

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 58.1 Plan 02: ContractMetadataWriterAgent Summary

**ContractMetadataWriterAgent seeds contract_metadata from settings.py on startup and atomically promotes front-month via asyncpg transaction when RollEvents arrive, with DLQ routing for all error paths**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T18:53:56Z
- **Completed:** 2026-04-02T18:57:23Z
- **Tasks:** 2
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- ContractMetadataWriterAgent implements the WriterAgent pattern with DB pool, Kafka consumer/producer, and graceful teardown
- `_seed_missing_contracts()` idempotently inserts futures instruments via ON CONFLICT DO NOTHING
- `_handle_roll_event()` atomically promotes front-month using asyncpg transaction (UPDATE old + UPSERT new) with exchange field copied from old row
- DLQ routing covers all 3 error paths: malformed payload, empty contracts, unknown old_contract
- DRY_RUN=true mode skips DB write but still validates DB read (old_row fetch) and publishes ContractUpdateEvent with dry_run=True
- 5 Golden Signals metrics at module level; 11 unit tests pass with full mock isolation

## Task Commits

1. **Task 1: ContractMetadataWriterAgent service** - `3035195` (feat)
2. **Task 2: Systemd unit and unit tests** - `b00e343` (feat)

## Files Created/Modified

- `services/contract_metadata_writer_agent.py` - ContractMetadataWriterAgent with seed, roll handling, DLQ routing
- `services/indicagent-contract-metadata-writer.service` - systemd unit (PYTHONUNBUFFERED=1, METRICS_PORT=9124, Restart=always)
- `tests/unit/test_contract_metadata_writer_agent.py` - 11 unit tests, fully mocked, no live DB
- `src/core/stream_keys.py` - Added topic_contract_updates() and topic_roll_dlq()
- `src/core/schemas/market_events.py` - Added ContractUpdateEvent schema

## Decisions Made

- `topic_contract_updates` and `topic_roll_dlq` added to stream_keys.py as blocking dependency (plan 01 not yet executed in this worktree — Rule 3 auto-fix)
- `ContractUpdateEvent` added to market_events.py for the same reason
- `asynccontextmanager` used in test fixtures for `conn.acquire()` context manager — avoids CLAUDE.md async mock dunder pitfall
- DRY_RUN path still fetches old_row to validate exchange copy logic, only skips DB write
- IBKR_RESTART_REQUIRED warning key in logger.warning() per plan spec

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added topic_contract_updates() and topic_roll_dlq() to stream_keys.py**
- **Found during:** Task 1 (ContractMetadataWriterAgent service)
- **Issue:** Plan 01 (which creates these functions) had not yet been executed in this worktree — imports would fail
- **Fix:** Added both topic functions to stream_keys.py following existing pattern
- **Files modified:** src/core/stream_keys.py
- **Verification:** Import succeeds, ruff passes
- **Committed in:** 3035195 (Task 1 commit)

**2. [Rule 3 - Blocking] Added ContractUpdateEvent to market_events.py**
- **Found during:** Task 1 (ContractMetadataWriterAgent service)
- **Issue:** Plan 01 adds ContractUpdateEvent schema; not present in worktree
- **Fix:** Added ContractUpdateEvent BaseModel with base_symbol, old_contract, new_contract, promoted_at fields
- **Files modified:** src/core/schemas/market_events.py
- **Verification:** Import succeeds, ruff passes
- **Committed in:** 3035195 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking dependencies from plan 01 not yet in worktree)
**Impact on plan:** Both required for import to succeed. Functionally identical to what plan 01 would have produced.

## Issues Encountered

None — all dependency gaps resolved cleanly with Rule 3 auto-fixes.

## User Setup Required

**After all phase 58.1 plans complete:**
1. `sudo cp /home/bg/dev/indicagent/services/indicagent-contract-metadata-writer.service /etc/systemd/system/`
2. `sudo systemctl daemon-reload`
3. `sudo systemctl enable --now indicagent-contract-metadata-writer`
4. Verify seeding: `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT symbol, base_symbol, exchange, is_front_month FROM contract_metadata;"`

## Next Phase Readiness

- Plan 03 (BarAuditorAgent session-aligned windows) can proceed — it subscribes to market.events.contract_update which is now defined
- ContractMetadataWriterAgent ready for deployment after DB migrations from plan 01 are applied
- No blockers

---
*Phase: 58.1-contract-lifecycle-automation*
*Completed: 2026-04-02*
