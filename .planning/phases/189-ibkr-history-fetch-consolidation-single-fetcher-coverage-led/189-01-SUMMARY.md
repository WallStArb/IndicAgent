---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 01
subsystem: ibkr-history-backfill
tags: [ohlcv_coverage, migration, single-writer, atomic-write, apr]
requires: []
provides:
  - ohlcv_coverage ledger (migration 432) bootstrapped from stored state
  - services/ohlcv_coverage_writer.py (CoverageDelta, existing_timestamps, upsert_coverage, record_fetch_outcome, reset_failures, FETCH_STATUSES, DESTINATION_*)
  - persist_chunk_atomically(..., coverage=CoverageDelta | None)
  - eight infra.* APR keys for the fetcher
affects: [189-02, 189-04, 189-08, 189-09]
tech-stack:
  added: []
  patterns: [third write under SET LOCAL ROLE bar_derivation_writer in the bars' transaction]
key-files:
  created:
    - production/migrations/432_ohlcv_coverage.sql
    - services/ohlcv_coverage_writer.py
    - tests/unit/test_ohlcv_coverage_migration_contract.py
    - tests/unit/scripts/test_ohlcv_coverage_atomic_write.py
    - tests/unit/test_ohlcv_coverage_writer_boundary.py
  modified:
    - scripts/infrastructure/backfill/_intraday_persist.py
    - tests/unit/scripts/test_intraday_persist.py
decisions:
  - "Coverage ledger migration is 432, not 430: phase 186 took 430 and 431 first. Plan 189-08's planned 431_retire_ibkr_history_lease_apr.sql must also renumber (433 or the next free)."
  - "persist_chunk_atomically refuses (ValueError, before any SQL) a chunk whose rows name a series other than its CoverageDelta."
  - "Live atomic test registers its synthetic ZZ189* symbol as an inactive instrument (ohlcv_request FK) and cleans the append-only request/archive rows under session_replication_role = replica, test-only."
metrics:
  duration: ~25 min
  completed: 2026-10-02
  tasks: 2
  files: 7
---

# Phase 189 Plan 01: ohlcv_coverage ledger and atomic third write summary

Coverage ledger `ohlcv_coverage` (migration 432) applied live and bootstrapped to 2,540 series from the archive, tradeable grid and SMART TRADES request log, with one writer module whose upsert commits in the same transaction as the request rows and bars.

## Tasks

| Task | Commit | What |
|------|--------|------|
| 1 | 94b05a333 | Migration 432: table, four CHECKs, grant, eight APR keys, bootstrap; static contract test |
| 2 (RED) | 41378863a | Failing tests: FakeConn order and counting, live atomic proof, boundary guard |
| 2 (GREEN) | c321d89c8 | `services/ohlcv_coverage_writer.py` and the coverage keyword on `persist_chunk_atomically` |

## Bootstrap

Timing per the performance SOP, measured read-only before applying: the 1h grid aggregate ran in 0.84 s under `EXPLAIN (ANALYZE, BUFFERS)`, the all-timeframe grid aggregate in 4.7 s and the archive aggregate in 0.8 s (counts over compressed chunks, no decompression). The full migration applied in 32 s.

Rows per timeframe after bootstrap:

| timeframe | series | sum row_count | row_count 0 | with last fetch |
|-----------|--------|---------------|-------------|-----------------|
| 15m | 557 | 60,444,555 | 0 | 557 |
| 1d | 931 | 3,863,639 | 0 | 931 |
| 1h | 558 | 16,594,777 | 0 | 557 |
| 1m | 233 | 8,992,596 | 0 | 233 |
| 4h | 2 | 2,184 | 0 | 0 |
| 5m | 259 | 77,365,983 | 19 | 252 |

The 19 zero-count 5m rows are request-only series (answered, no stored tradeable bars). 2,305 rows across 1d/5m/15m/1h (acceptance needed >= 900).

HPQ and BBY:

| symbol | tf | earliest | latest | row_count | last_fetched_at | status |
|--------|----|----------|--------|-----------|-----------------|--------|
| BBY | 15m | 2006-10-02 13:30 | 2026-10-01 18:45 | 130,284 | 2026-10-01 19:08 | ok |
| BBY | 1d | 2006-10-02 | 2026-09-30 | 5,027 | 2026-10-01 08:36 | ok |
| BBY | 1h | 2006-10-02 13:30 | 2026-10-01 19:00 | 35,089 | 2026-10-02 09:56 | ok |
| HPQ | 15m | 2006-10-05 13:30 | 2026-10-01 19:45 | 130,243 | 2026-10-02 12:08 | ok |
| HPQ | 1d | 2006-10-02 | 2026-09-30 | 5,027 | 2026-10-01 08:42 | ok |
| HPQ | 1h | 2006-10-05 13:30 | 2026-10-01 19:00 | 35,073 | 2026-10-02 11:59 | ok |

HPQ 15m now reads 130k (the derived grid has caught up since the plan's 35k-archive / 0-grid observation; GREATEST of the two counts is taken). All consecutive_failures are 0. Acceptance checks: `infra.ibkr.history_request_timeout` = 900, `bar_derivation_writer` has UPDATE (and not DELETE) on the ledger.

## Deviations from plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] Migration number 430 taken**
- Found during: Task 1. `430_drop_forward_returns_retire_lookahead_keys.sql` and `431_retire_cluster_max_corr.sql` already exist (phase 186).
- Fix: shipped as `432_ohlcv_coverage.sql`, `changed_by 'migration_432'`; contract test reads 432. The plan said to use the next free number everywhere in the phase; I did not edit other 189 plan files (out of this plan's file scope). Plan 189-08 references `431_retire_ibkr_history_lease_apr.sql` and must pick a new number (433 or later); plans 02, 04 and 09 call the APR seeds "migration 430", meaning 432.

**2. [Rule 3 - Blocking] Live-test cleanup against append-only tables and an FK**
- Found during: Task 2. `ohlcv_request` has an FK to `instruments` and an append-only trigger; `ohlcv_intraday_raw_archive` is append-only too (`bar_derivation_append_only`). The plan's plain DELETE cleanup cannot work.
- Fix: the fixture inserts the synthetic `ZZ189xxxxxx` symbol as an inactive instrument, and cleanup deletes request and archive rows under `SET LOCAL session_replication_role = replica` (precedent: `tests/integration/test_classification_schema.py`), then the instrument. A first run's failed teardown left one synthetic set behind; it was removed by hand with the same statements and the post-run check shows 0 rows in all four tables.

**3. [Rule 2 - Correctness] Series mismatch guard**
- `persist_chunk_atomically` raises ValueError before opening the transaction when a chunk's rows belong to a different (symbol, timeframe) than its CoverageDelta, so the ledger cannot silently credit the wrong series. Duplicate timestamps within one chunk count once.

**4. [Rule 3] Test helper fixes**
- The contract test strips whole-line SQL comments only (a description legitimately contains `--reset-failures`), and accepts `[conventional]` provenance (the plan seeds `inter_item_pause_s` as `[conventional]` while the test spec listed only two tags).
- Boundary test function renamed to `test_coverage_writer_allow_list_has_no_stale_entries` (the pre-commit duplicate-test-name check).

## TDD gate compliance

RED `41378863a` (test) precedes GREEN `c321d89c8` (feat). No refactor commit needed.

## Verification

`.venv/bin/pytest tests/unit/scripts/test_intraday_persist.py tests/unit/scripts/test_ohlcv_coverage_atomic_write.py tests/unit/test_ohlcv_coverage_migration_contract.py tests/unit/test_ohlcv_coverage_writer_boundary.py tests/unit/test_market_data_ohlcv_writer_boundary.py tests/unit/test_market_data_ohlcv_boundary.py -q -rs`: 35 passed, 0 skipped (the 3 live-DB cases ran). Every unit test module that imports `_intraday_persist`, `ohlcv_observation_writer` or `intraday_raw_archive` passes. The default `coverage=None` path issues the same statements as before, so the running todo 449 lane (which imports the helper) is unaffected by a restart.

## Threat flags

None beyond the plan's register. The grant is SELECT, INSERT, UPDATE only (T-189-02, pinned by the contract test).

## Self-Check: PASSED

- FOUND: production/migrations/432_ohlcv_coverage.sql, services/ohlcv_coverage_writer.py, tests/unit/test_ohlcv_coverage_migration_contract.py, tests/unit/scripts/test_ohlcv_coverage_atomic_write.py, tests/unit/test_ohlcv_coverage_writer_boundary.py
- FOUND commits: 94b05a333, 41378863a, c321d89c8
