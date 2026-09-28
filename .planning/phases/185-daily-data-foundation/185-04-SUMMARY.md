---
phase: 185-daily-data-foundation
plan: 04
subsystem: database
tags: [d9-quarantine, bar-quality-flag, provenance, apr, read-boundary]

# Dependency graph
requires: []
provides:
  - bar_quality_flag / bar_derivation_batch tables, migration 381 (applied live 2026-09-27)
  - bar_derivation_writer NOLOGIN role with DML on both tables
  - market_data_ohlcv_tradeable anti-join hiding quarantined bars (11 columns unchanged)
  - market_data_ohlcv_scrub_input view (D2a/D5 read boundary, quarantined included)
  - nine threshold.bar_scrub.*/infra.bar_scrub.* APR keys seeded (changed_by migration_381)
  - services/bar_derivation_batch.py open_batch/close_batch (+sync twins) and current_code_commit()
affects: [185-05, 185-10, 185-12, 185-16, 185-17, 185-20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Quarantine as side-table anti-join: never UPDATE compressed chunks (todo 155), never delete raw bars (D-09)"

key-files:
  created:
    - production/migrations/381_bar_quality_flag.sql
    - services/bar_derivation_batch.py
    - tests/unit/test_bar_quality_flag_migration_contract.py
    - tests/unit/services/test_bar_derivation_batch.py
    - tests/integration/test_bar_quality_flag_quarantine.py
  modified: []

key-decisions:
  - "No decompress_chunk anywhere: the legacy status copy reads over compressed chunks and inserts into a plain table, so the compressed-hypertable VACUUM rule does not apply"
  - "Todo 347's unused partial index dropped by the same migration (folds the todo)"
  - "JSON parameters passed as json.dumps strings with ::jsonb casts in bar_derivation_batch.py so bare connections without the jsonb codec stay correct"

patterns-established:
  - "One derivation run = one bar_derivation_batch row opened before writing and closed completed/failed; every flag row carries its batch_id"

requirements-completed: [D-08, D-09, D-12]

# Metrics
duration: about 45 min inline (orchestrator session)
completed: 2026-09-27
---

# Plan 185-04: bar_quality_flag quarantine summary

**Migration 381 applied live (EXPLAIN before/after recorded), the read boundary now hides quarantined bars, and every derivation run gets a provenance batch helper**

## Performance
- **Duration:** about 45 min (task 1 contract suite, task 2 apply + measure + integration test, task 3 helper)
- **Completed:** 2026-09-27
- **Tasks:** 3

## EXPLAIN numbers (migration 381 header records the same)
- S0 1d read shape: baseline 1042.819 ms, anti-join proxy 705.333 ms, after-apply 1056.452 ms (+1.3%, inside the 20% gate)
- SPY 5m 2024 read: baseline 10.162 ms, proxy 65.808 ms, after-apply 8.044 ms (faster than baseline)

## Acceptance verified live
- 567 legacy price_sanity_status rows copied, 67 quarantined (confirmed_corrupt)
- idx_market_data_ohlcv_price_sanity_unaudited gone (pg_indexes count 0)
- 9 bar_scrub APR keys present in config_state; three-block seed shape with changed_by migration_381
- 3 sampled quarantined bars present in raw and absent from the tradeable view; non-quarantined legacy-flagged bars still visible; 11-column view contract intact

## Task commits
1. **Task 1: migration 381 + contract suite** - `52a697f73`
2. **Task 2: after-numbers header + live integration test** - `7fadca257`
3. **Task 3: bar_derivation_batch helper + fake-conn tests** - `fab80260c`

**Plan metadata:** this commit

## Deviations from plan
- Task 1's first commit momentarily carried a red contract test (a piped `pytest | tail && git commit` masked the failure; fixed and amended before push). Guard used ever after: `test ${PIPESTATUS[0]} -eq 0`
- The integration test hardcodes `_LIVE_DB_URL` (matching 185-02's test) rather than Settings, because the root conftest repoints settings.database_url at indicagent_test, whose rebuilt schema has no market data

## Issues encountered
- None beyond the above.

## User setup required
None.

## Next phase readiness
- Plans 05/10 read threshold.bar_scrub.* through ConfigService and write flags through bar_derivation_writer with open_batch/close_batch provenance
- Plan 16's D-28 check reports the active quarantine_rules list

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-27*
