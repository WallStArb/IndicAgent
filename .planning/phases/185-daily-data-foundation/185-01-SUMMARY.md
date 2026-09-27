---
phase: 185-daily-data-foundation
plan: 01
subsystem: database
tags: [timescaledb, compression, ohlcv, write-rates, fixtures]

# Dependency graph
requires: []
provides:
  - Known-answer bar fixtures under tests/fixtures/bars/ (2026-09-26 dry-run report, price_sanity_status rows, MRNA/ALMS seam windows, SPY half-day/DST 5m, SPY 1d 2024)
  - Shared test scaffolding tests/unit/bars/_builders.py and the package skeletons
  - ops_measure_ohlcv_write_rates.py scratch-hypertable measurement harness
  - 185-01-MEASUREMENTS.md: method rates, role result, recommendation for plans 12 and 17
affects: [185-10, 185-12, 185-15, 185-17, 185-18]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scratch hypertable measurement harness: setup mirrors the live table's exact shape, fill from the tradeable view, compress old chunks, time each DML method with size and compressed-chunk deltas, teardown with existence guards"

key-files:
  created:
    - tests/fixtures/bars/corrupt_1d_dry_run_2026_09_26.txt
    - tests/fixtures/bars/price_sanity_status_rows.csv
    - tests/fixtures/bars/seam_candidates_mrna_alms.csv
    - tests/fixtures/bars/spy_5m_2025_11_28_half_day.csv
    - tests/fixtures/bars/spy_5m_dst_2025_03_10_2025_11_03.csv
    - tests/fixtures/bars/spy_1d_2024.csv
    - tests/fixtures/bars/README.md
    - tests/unit/bars/_builders.py
    - scripts/ops/bars/ops_export_known_answer_fixtures.py
    - scripts/ops/bars/ops_measure_ohlcv_write_rates.py
    - .planning/phases/185-daily-data-foundation/185-01-MEASUREMENTS.md
  modified:
    - tests/unit/test_market_data_ohlcv_boundary.py
    - .planning/todos/pending/155-price-sanity-status-historical-backfill.md
    - .planning/todos/pending/347-price-sanity-index-column-order-mismatch-bar-auditor-query.md
    - .planning/todos/pending/052-adversarial-data-error-hunt.md

key-decisions:
  - "Plan 12 (D2b rewrite) uses DELETE + reinsert per (symbol, tf) segment in one transaction: 90-111k rows/s measured, minutes for the whole universe, and native upsert measured worst on disk"
  - "Plan 17 (nightly 1d) uses native upsert for the changed-rows write; a full 3.87M-row pass is about a minute"
  - "A NOLOGIN role with table grants can DML compressed chunks (TimescaleDB 2.27.1), so D-05-style writer roles are enforceable on market_data_ohlcv itself"

patterns-established:
  - "Conflict-free reinserts on a uniform grid: shift timestamps by a value coprime to the grid (+17 min on 1h bars; +60 self-conflicts, +30 collides on mixed :00/:30 grids)"

requirements-completed: [D-10, D-12, D-15, D-24]

# Metrics
duration: task 1 earlier same day; task 2 about 1 h including quota-outage salvage (harness run about 10 min)
completed: 2026-09-27
---

# Plan 185-01: known-answer fixtures and write-rate measurements summary

**Bar known-answer fixtures committed for DB-free rule tests, plus measured compressed-hypertable write rates and role privileges that fix the D2b/D2 write methods for plans 12 and 17**

## Performance

- **Duration:** task 2 about 1 h wall (harness run about 10 min: fill 3.08M rows, compress 122 chunks, five timed methods, two EXPLAIN samples)
- **Started:** 2026-09-27 (task 1 committed earlier that day)
- **Completed:** 2026-09-27
- **Tasks:** 2
- **Files modified:** 18 per plan frontmatter

## Accomplishments
- The 2026-09-26 dry-run report and every fixture series live under tests/fixtures/bars/ with shared builders, so scrub-rule tests run without a database
- Todos 155, 347 and 052 keep their pre-fold bodies for provenance
- 185-01-MEASUREMENTS.md records the five-method rate table, the EXPLAIN batch-path evidence, the contention observation, and the extrapolations (8M 1h ~88 s ideal, 27M 15m ~4.1 min, 3.87M 1d ~59 s, each with 10x headroom)
- The A7 role question is answered: writer-role separation works on the compressed hypertable

## Task commits

1. **Task 1: fixtures, scaffolding, harness skeleton** - `1ef8941c6`
2. **Task 2: run measurements, MEASUREMENTS.md, teardown guard** - `757e4f04b`

**Plan metadata:** this commit (summary, roadmap tick, state)

## Decisions made
- DELETE + reinsert for plan 12's segment rewrite; native upsert only for plan 17's nightly changed rows (see MEASUREMENTS Recommendation)
- Ran task 2 inline in the orchestrator session: the 5-hour quota window killed the executor subagent, but the harness is pure local compute plus DB work (owner instruction relayed 2026-09-27)

## Deviations from plan

None - plan executed as written.

## Issues encountered
- The first executor died in the 5-hour quota window before running the harness; task 2 was picked up inline instead of waiting for the reset
- The harness's role check originally shifted COPY timestamps by +60 min, which lands every 1h bar on its own next bar (guaranteed PK self-conflict); fixed to +17 min before the successful run
- teardown() raised UndefinedObject at exit because role_check() had already dropped the role; the `| tee` pipeline masked the nonzero exit. Cleanup had already succeeded (verified by direct psql counts of 0); the guard was added in the task 2 commit

## User setup required
None.

## Next phase readiness
- Wave 1 continues: 185-02 (D1 migration and COPY writer), 185-03 (provider), 185-04 (scrub scaffolding), dispatched after the quota reset (01:14 UTC 2026-09-28)
- Plans 10, 12, 15 and 17 cite 185-01-MEASUREMENTS.md for their write-method choices

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-27*
