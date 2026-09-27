---
phase: 185-daily-data-foundation
plan: 02
subsystem: database
tags: [d1, ohlcv-observation, append-only, roles, copy-writer, migration]

# Dependency graph
requires: []
provides:
  - ohlcv_request / ohlcv_observation append-only D1 tables live (migration 380), UPDATE/DELETE/TRUNCATE raise for every role
  - NOLOGIN roles ohlcv_observation_writer (INSERT, SELECT) and bar_derivation_writer (SELECT)
  - View ohlcv_venue_head (moved-name inventory, D-20 evidence, D-25 input)
  - services/ohlcv_observation_writer.py: ObservationSink, AsyncObservationSink, new_fetch_run_id
  - APR keys infra.bar_campaign.client_ids [47,48,49], infra.ibkr_history_lease.nightly_wait_minutes 60, infra.ibkr_history_lease.priority_wait_minutes 240, infra.ohlcv_observation.copy_batch_rows 50000
  - Repaired tests/integration/ rebuild (baseline bump to 2026-09-27, controlled_vocabulary seed, migration 328 replay-order fix)
affects: [185-03, 185-09, 185-13, 185-14, 185-15, 185-17, 185-19, 185-20, 185-21, 185-22, 185-24]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SET LOCAL ROLE needs a top-level transaction: refuse flush on an open caller connection (a savepoint-demoted transaction leaks the role past the flush)"

key-files:
  created:
    - production/migrations/380_ohlcv_observation_store.sql
    - services/ohlcv_observation_writer.py
    - tests/unit/test_ohlcv_observation_migration_contract.py
    - tests/unit/services/test_ohlcv_observation_writer.py
    - tests/integration/test_ohlcv_observation_store.py
    - tests/integration/fixtures/schema_baseline_2026-09-27.sql
    - tests/integration/fixtures/schema_baseline_2026-09-27_hypertables.sql
    - tests/integration/fixtures/seed_instruments_2026-09-27.sql
    - tests/integration/fixtures/seed_tag_vocabulary_2026-09-27.sql
    - tests/integration/fixtures/seed_controlled_vocabulary_2026-09-27.sql
  modified:
    - production/migrations/328_concept_registry_phase148_placement_verdict.sql
    - tests/integration/conftest.py

key-decisions:
  - "Four APR keys seeded, not five: the interfaces block (the contract dependents use) defines four; the task text's 'five' and the count-of-5 acceptance SQL were a plan miscount"
  - "Both sinks refuse to flush on a connection with an open transaction; the sync sink commits the SELECT 1 health check so the write transaction stays top-level"
  - "TRUNCATE on the FK-referenced side is refused by the planner (FeatureNotSupported) before the trigger fires; the integration test accepts either refusal"

patterns-established:
  - "D1 COPY writer: buffer duck-typed RequestRecords, flush requests-first under SET LOCAL ROLE in one transaction"

requirements-completed: [D-01, D-02, D-05, D-20]

# Metrics
duration: about 40 min inline (orchestrator session; quota window kept subagents down)
completed: 2026-09-27
---

# Plan 185-02: D1 raw observation store summary

**Migration 380 live and committed in the same step; both COPY writers proven against the live schema; the integration suite itself repaired along the way**

## Performance
- **Duration:** about 40 min (task 1 about 15, task 2 about 25 including the suite repair)
- **Completed:** 2026-09-27
- **Tasks:** 2

## Accomplishments
- D1 exists live: append-only ohlcv_request (any timeframe, per-request outcome) and ohlcv_observation (1d only, finite prices), 4 non-internal triggers, both NOLOGIN roles, ohlcv_venue_head view
- ObservationSink/AsyncObservationSink: requests-first COPY under the writer role, orphan/non-finite/intraday refusals, auto-flush at max_buffer_rows (sync)
- The integration test proved live: UPDATE/DELETE/TRUNCATE raise, bar_derivation_writer reads but cannot INSERT

## Task commits
1. **Task 1: migration 380 + contract test** - `f3d584789`
2. **Suite repair (unplanned, prerequisite)** - `c19bcb545`
3. **Task 2: writers + unit/integration tests** - `1e3477de6`

**Plan metadata:** this commit

## Decisions made
- Ran both tasks inline in the orchestrator (owner instruction 2026-09-27: do not idle; inline execution survives the quota window that kills subagent spawns)
- Deviation: four APR keys, not five (interfaces block is the contract; recorded here rather than inventing a fifth key to satisfy a grep)
- The whole tests/integration/ suite had been broken since migration 322 (empty controlled_vocabulary after the schema-only baseline); repaired via the conftest's own sanctioned baseline-bump path plus an idempotent widening duplicated into 328 (329 widens the CHECK 328 needs but sorts after it)

## Deviations from plan
- APR key count (see above); everything else per plan

## Issues encountered
- SET LOCAL ROLE leak: psycopg's conn.transaction() demotes to a savepoint when the health check's implicit transaction is open, trapping the role past flush; fixed by committing the health check and refusing flush on an open connection (found by the integration test, unit-tested)
- TRUNCATE on ohlcv_request is refused by the FK planner before the trigger; test accepts either exception

## User setup required
None.

## Next phase readiness
- Wave 1 continues with 185-03 (provider request records) and 185-04 (scrub scaffolding), scheduled via the 21:21 EDT cron dispatch after the quota reset
- Every IBKR campaign plan (09/13/14/15/17/19/20/21/22/24) imports ObservationSink/AsyncObservationSink and new_fetch_run_id from services/ohlcv_observation_writer.py

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-27*
