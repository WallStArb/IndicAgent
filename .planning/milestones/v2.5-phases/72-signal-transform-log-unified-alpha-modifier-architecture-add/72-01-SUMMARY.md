---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "01"
subsystem: database
tags: [migration, timescaledb, signal-transform-log, graduation]
dependency_graph:
  requires: []
  provides: [signal_transform_log hypertable, transform_graduation table]
  affects: [pipeline persistence, GraduationComputeAgent, GraduationWriterAgent]
tech_stack:
  added: []
  patterns: [TimescaleDB hypertable, analytical table with UPSERT UNIQUE constraint]
key_files:
  created:
    - production/migrations/069_signal_transform_log.sql
    - production/migrations/070_transform_graduation.sql
  modified: []
decisions:
  - "DOUBLE PRECISION used for multiplier (PostgreSQL canonical form of FLOAT)"
  - "if_not_exists => TRUE on create_hypertable for safe re-runs"
  - "CONSTRAINT uq_transform_graduation named explicitly (not inline UNIQUE) for reliable ON CONFLICT targeting"
metrics:
  duration: "59s"
  completed: "2026-04-25T12:52:41Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 72 Plan 01: DB Migrations — Signal Transform Log Summary

**One-liner:** Two SQL migration files creating the signal_transform_log hypertable and transform_graduation analytical table for Phase 72 dual-write infrastructure.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create migration 069_signal_transform_log.sql | fa6c075a | production/migrations/069_signal_transform_log.sql |
| 2 | Create migration 070_transform_graduation.sql | cc5ab506 | production/migrations/070_transform_graduation.sql |

## What Was Built

**069_signal_transform_log.sql** — TimescaleDB hypertable that captures one row per signal per transform per version. Foundation for Phase 72 dual-write log. Key design:
- Hypertable partitioned on `ts` (same pattern as `intelligence_features`)
- UNIQUE index `idx_stl_identity` on `(signal_id, transform_id, transform_version)` — one row per signal per transform per version
- Evaluation index `idx_stl_eval` on `(transform_id, segment_key, ts)` for 90-day rolling graduation queries
- `is_shadow=TRUE` default — all Phase 1 writes are in shadow mode
- `multiplier DOUBLE PRECISION` — composes via product; 0.0 = signal killed

**070_transform_graduation.sql** — Analytical table (NOT a hypertable) holding per-segment statistical evidence for transform graduation. Key design:
- UNIQUE constraint `uq_transform_graduation` on `(transform_id, transform_version, segment_key)` enables UPSERT from GraduationWriterAgent
- Lookup index `idx_transform_graduation_lookup` on `(is_graduated, transform_id)` for startup cache population (Phase 2)
- All 6 graduation dimensions as first-class columns: `spearman_rho`, `spearman_p`, `calibration_max_error`, `cvar_bottom_decile`, `val_rho`, `sharpe_delta`
- `expires_at` column enforces quarterly re-proof (evaluated_at + 90 days)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None — these are schema-only migration files with no runtime stub behavior.

## Threat Flags

None — these are DDL-only migration files. No new network endpoints, auth paths, or trust boundary changes introduced. Tables will be written to by internal pipeline agents only (no direct external access).

## Self-Check: PASSED

Files created:
- `production/migrations/069_signal_transform_log.sql` — FOUND
- `production/migrations/070_transform_graduation.sql` — FOUND

Commits:
- `fa6c075a` — FOUND (feat(72-01): add signal_transform_log hypertable migration)
- `cc5ab506` — FOUND (feat(72-01): add transform_graduation analytical table migration)
