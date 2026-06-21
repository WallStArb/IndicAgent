---
phase: 137-feature-factory
plan: 1
subsystem: persistence-foundation
tags: [timescaledb, hypertable, apr, migration, config]
dependency_graph:
  requires: []
  provides:
    - feature_vectors hypertable (42 typed columns, no JSONB, 3-month chunks)
    - backfill_status checkpoint table
    - 16 feature.* APR keys in config_state
    - alpha.vector.v1_quant.members APR key
    - alpha. OPS prefix registered in ConfigService
  affects:
    - src/config/config_service.py (OPS_PREFIXES expanded)
    - production/migrations/ (migration 155 added)
tech_stack:
  added: []
  patterns:
    - TimescaleDB hypertable with typed float columns (no JSONB)
    - APR seed migration: ON CONFLICT DO NOTHING idempotent inserts
    - OPS prefix registration for new APR namespace
key_files:
  created:
    - production/migrations/155_feature_vectors.sql
  modified:
    - src/config/config_service.py
decisions:
  - "Column count is 42 (6 structural + 36 features), not 41 as stated in plan frontmatter; CONTEXT.md specifics list 36 features (14+4+7+3+5+3) not 35; DDL binding reference takes precedence over text description"
  - "ALTER TABLE SET timescaledb.compress required before add_compression_policy in TimescaleDB 2.27.1; migration updated to include this step for idempotency"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_changed: 2
---

# Phase 137 Plan 1: Schema + APR Foundation Summary

**One-liner:** `feature_vectors` TimescaleDB hypertable (42 typed columns, no JSONB, CHECK-constrained regime_label_source) with 16 feature.* and alpha.vector.v1_quant.members APR seeds, plus `alpha.` registered as ConfigService OPS prefix.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register alpha. prefix in ConfigService OPS_PREFIXES | 6b9ffbd4 | src/config/config_service.py |
| 2 | Write migration 155 - feature_vectors + backfill_status + APR seeds | 42492a3b | production/migrations/155_feature_vectors.sql |

## Verification Results

All acceptance criteria met:

- **Migration idempotent:** ran twice, both exit 0 with IF NOT EXISTS / ON CONFLICT DO NOTHING
- **Column count:** 42 total (6 structural + 36 feature floats; see Deviations for context)
- **No JSONB:** 0 JSONB columns in feature_vectors
- **Hypertable:** confirmed via timescaledb_information.hypertables
- **3-month chunks:** created via create_hypertable with chunk_time_interval = INTERVAL '3 months'
- **6-month compression:** ALTER TABLE SET timescaledb.compress + add_compression_policy INTERVAL '6 months'
- **CHECK constraint T2:** INSERT with regime_label_source='smoothed' raises CHECK violation (T2 mitigated)
- **backfill_status:** has fetch_complete boolean NOT NULL DEFAULT false column
- **16 feature.* APR keys:** all present in config_state
- **alpha.vector.v1_quant.members:** value = momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum
- **alpha. in OPS_PREFIXES:** True (T1 mitigated)

## Threat Model Resolution

- **T1 (alpha. prefix missing from OPS_PREFIXES):** MITIGATED - added in Task 1; ConfigService.set() now accepts alpha.* keys
- **T2 (regime_label_source allows 'smoothed'):** MITIGATED - CHECK constraint in DDL rejects smoothed labels at DB layer; verified with failing INSERT

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TimescaleDB 2.27.1 requires ALTER TABLE before add_compression_policy**

- **Found during:** Task 2 migration execution
- **Issue:** `SELECT add_compression_policy(...)` raised `ERROR: columnstore not enabled on hypertable "feature_vectors"` in TimescaleDB 2.27.1. The DDL in RESEARCH.md assumed an older API pattern.
- **Fix:** Added `ALTER TABLE feature_vectors SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,tf', timescaledb.compress_orderby = 'bar_ts ASC')` before `add_compression_policy`. This is idempotent - re-running emits a NOTICE but does not error.
- **Files modified:** production/migrations/155_feature_vectors.sql
- **Commit:** 42492a3b

**2. [Rule 1 - Documentation] Column count is 42, not 41**

- **Found during:** Task 2 verification
- **Issue:** Plan frontmatter states "41 total columns" and "35 features", but CONTEXT.md `<specifics>` lists 36 features across 6 groups (14+4+7+3+5+3=36). The binding DDL reference (RESEARCH.md Code Examples) contains exactly these 36 feature columns, producing 42 total (6 structural + 36 features).
- **Fix:** Implemented per binding DDL reference (42 columns). Plan acceptance criterion `returns 41` is a documentation error - the actual spec requires 42.
- **Impact:** None - the feature list itself is correct and complete per CONTEXT.md binding spec.

**3. [Rule 3 - Blocker] .venv symlink needed in worktree for pre-commit hooks**

- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT=worktree path. No .venv exists in worktree.
- **Fix:** Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree root. This is local worktree state, not committed.
- **Files modified:** (symlink, not tracked)

## Self-Check

Files created:
- [x] FOUND: production/migrations/155_feature_vectors.sql
- [x] FOUND: src/config/config_service.py (modified, not created)

Commits exist:
- [x] FOUND: 6b9ffbd4 (alpha. prefix)
- [x] FOUND: 42492a3b (migration 155)

DB state verified:
- [x] feature_vectors hypertable exists with 42 columns
- [x] regime_label_source CHECK constraint blocks 'smoothed'
- [x] backfill_status exists with fetch_complete column
- [x] 16 feature.* + 1 alpha.* APR keys in config_state

## Self-Check: PASSED
