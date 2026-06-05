---
phase: 097-agent-memory
plan: "01"
subsystem: database
tags: [pgvector, timescaledb, schema, memory, renaissance-constraints]
dependency_graph:
  requires: []
  provides:
    - memory_system_state table (epoch registry for C-01)
    - memory_episodes_raw hypertable (write-only, live pipeline)
    - memory_episodes_labeled hypertable (HNSW recall index)
    - memory_calibration_promoted table (C-03 N>=30 gate)
    - memory_calibration_spc hypertable (drift alerting)
    - memory_regime_transitions table (Markov state machine)
  affects:
    - Wave 2 backend (MemoryClient, MemoryEpisodeWriter reads/writes these tables)
    - Wave 3 nightly batch (promotion job writes memory_calibration_promoted)
tech_stack:
  added: []
  patterns:
    - pgvector HNSW index (m=32, ef_construction=128) for approximate nearest-neighbor recall
    - TimescaleDB hypertable + compression policy for episodic and SPC timeseries
    - ENUM-guarded DO $$ EXCEPTION WHEN duplicate_object pattern for idempotent type creation
    - Structural CHECK constraint (sample_n >= 30) instead of application-layer guard
    - Partial UNIQUE INDEX (WHERE ts_end IS NULL) for single-open-period structural guarantee
key_files:
  created:
    - production/migrations/118_agent_memory_schema.sql
  modified: []
decisions:
  - Migration number 118 used (plan specified 114 but migrations 114-117 already existed)
  - memory_regime_transitions kept as regular table (not hypertable) to preserve UNIQUE INDEX WHERE ts_end IS NULL semantics -- TimescaleDB requires partition key in all UNIQUE indexes on hypertables, which would invalidate the single-open-period structural guarantee
metrics:
  duration_minutes: 15
  completed_date: "2026-06-04"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
---

# Phase 097 Plan 01: Agent Memory Schema Summary

**One-liner:** pgvector-native memory schema with 6 tables, 3 ENUMs, HNSW recall index, and all 4 Renaissance constraints (C-01-C-04) encoded structurally in DDL.

## What Was Built

Migration `118_agent_memory_schema.sql` creates the complete agent memory database substrate:

**ENUMs (3):**
- `memory_episode_kind` -- episodic | disagreement | relational
- `memory_regime_label` -- ranging | trending_up | trending_down
- `memory_spc_stat` -- 5 values for SPC stat rows

**Tables (6):**

| Table | Type | Key Feature |
|-------|------|-------------|
| `memory_system_state` | Regular (single-row) | C-01 epoch source; single-row CHECK; seeded |
| `memory_episodes_raw` | Hypertable on ts | Write-only; chk_raw_outcome with D-09 9-value set; C-01/C-02/C-04 columns |
| `memory_episodes_labeled` | Hypertable on ts | HNSW (m=32, ef=128); embedding NOT NULL; 30-day compression |
| `memory_calibration_promoted` | Regular (append-only) | chk_cal_sample_n CHECK (sample_n >= 30) -- C-03 structural gate |
| `memory_calibration_spc` | Hypertable on ts | EWMA + CUSUM + KS columns; 7-day compression |
| `memory_regime_transitions` | Regular table | UNIQUE INDEX mem_reg_open WHERE ts_end IS NULL; chk_transition_probs_sum |

**All constraints confirmed live:**
- `chk_raw_outcome` and `chk_labeled_outcome` enforce exact D-09 outcome set (never win/loss/break_even)
- `chk_cal_sample_n CHECK (sample_n >= 30)` -- INSERT with sample_n=10 rejected at DB layer
- `chk_win_rate` on regime transitions
- `chk_transition_probs_sum` -- Markov probabilities must sum to 1.0 +/- 0.001

**Idempotency:** Migration applies cleanly on both fresh and already-migrated DB. Second run completes with BEGIN...COMMIT and no errors.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migration number conflict**
- **Found during:** Task 1 setup
- **Issue:** Plan specified migration 114, but migrations 114-117 already existed in `production/migrations/`
- **Fix:** Used migration number 118 (next available)
- **Files modified:** production/migrations/118_agent_memory_schema.sql
- **Commit:** 03358879

**2. [Rule 1 - Bug] TimescaleDB UNIQUE INDEX partition key constraint**
- **Found during:** Task 2 -- first migration run attempt
- **Issue:** `CREATE UNIQUE INDEX mem_reg_open ON memory_regime_transitions (symbol, timeframe) WHERE ts_end IS NULL` failed because TimescaleDB requires the partition key (`ts_start`) in every UNIQUE index on a hypertable. Including `ts_start` in the unique index would break the single-open-period guarantee (two open rows with different `ts_start` would both pass the constraint).
- **Fix:** Changed `memory_regime_transitions` from a hypertable to a regular table. It is low-volume (one row per regime period per symbol/timeframe) and does not need time chunking. The structural guarantee of at most one open period per (symbol, timeframe) is preserved exactly as designed.
- **Files modified:** production/migrations/118_agent_memory_schema.sql
- **Commit:** 03358879 (same commit, fixed before commit)

## Self-Check

**Created files:**
- [x] `production/migrations/118_agent_memory_schema.sql` -- FOUND

**Live DB verification:**
- [x] `\dt memory_*` lists exactly 6 tables
- [x] `\dT memory_*` lists 3 ENUMs
- [x] `SELECT count(*) FROM memory_system_state` returns 1
- [x] `\d memory_episodes_labeled` shows `mem_labeled_hnsw` using hnsw
- [x] `\d memory_episodes_labeled` shows `embedding vector(768) NOT NULL`
- [x] INSERT with sample_n=10 into memory_calibration_promoted fails on chk_cal_sample_n
- [x] `\d memory_regime_transitions` shows `mem_reg_open UNIQUE ... WHERE ts_end IS NULL`
- [x] compression_enabled=true for memory_episodes_labeled and memory_calibration_spc
- [x] Second migration run completes without errors (idempotent)

## Self-Check: PASSED
