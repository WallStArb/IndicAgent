---
phase: 130-script-rewriting
plan: "01"
subsystem: config
tags: [apr, config-service, migration, ops-prefixes]
dependency_graph:
  requires: []
  provides: [APR-keys-130, ui-ops-prefix, weights-ops-prefix]
  affects: [signal_writer, lifecycle_writer, signal_tracker, signal_auditor, api-signals]
tech_stack:
  added: []
  patterns: [apr-migrate-as-you-go, idempotent-migration]
key_files:
  created:
    - production/migrations/142_phase130_apr_seeds.sql
  modified:
    - src/config/config_service.py
decisions:
  - "Added ui. and weights. to OPS_PREFIXES enabling ConfigService.set() writes for both namespaces"
  - "22 APR keys seeded as operational/UX parameters (NOT ML targets); ON CONFLICT DO NOTHING for idempotency"
  - "config_history populated alongside config_schema + config_state for full audit trail"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 2
---

# Phase 130 Plan 01: APR Foundation — OPS_PREFIXES + Migration 142

APR foundation for Phase 130 write-path rewrite: extended OPS_PREFIXES to include `ui.` and `weights.`, and seeded all 22 new Phase 130 parameter keys into config_schema + config_state via migration 142.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add ui. and weights. to OPS_PREFIXES | db09d243 | src/config/config_service.py |
| 2 | Create migration 142 seeding 22 Phase 130 APR keys | 58a60134 | production/migrations/142_phase130_apr_seeds.sql |

## What Was Done

### Task 1: OPS_PREFIXES Extension

Added `"ui."` and `"weights."` to the `OPS_PREFIXES` ClassVar in `ConfigService`. Before this change, `ui.signals.*` keys could not be written via `ConfigService.set()` (the prefix validation gate would reject them), and `weights.*` keys were only writable via direct SQL. Both prefixes are now first-class OPS namespaces alongside the 9 pre-existing entries.

### Task 2: Migration 142

Created and applied `production/migrations/142_phase130_apr_seeds.sql` with all 22 keys across 5 namespaces:

| Namespace | Keys | Purpose |
|-----------|------|---------|
| `feature.signal_writer.*` | 3 | Batch size, flush interval, buffer cap |
| `feature.lifecycle_writer.*` | 3 | Batch size, flush interval, buffer cap |
| `feature.signal_tracker.*` | 4 | Bootstrap window days + max attempts |
| `threshold.signal_tracker.*` | 1 | Staleness score threshold |
| `feature.signal_auditor.*` | 1 | Audit lookback hours |
| `ui.signals.*` | 10 | API windows, confidence gates, result limits |

All keys use `ON CONFLICT (config_key) DO NOTHING` — idempotent and re-runnable. No DROP statements in this file (migration 143 owns the DROP sequence). `config_history` populated for full audit trail with `changed_by='migration_142'`.

## Verification

- `ConfigService.OPS_PREFIXES` contains `"ui."` and `"weights."` (11 entries total)
- `config_state` count query returns 22 for all Phase 130 key patterns
- `ui.signals.min_confidence` = `0.40` (empirical breakeven threshold)
- Migration is idempotent — re-running inserts 0 rows without error

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `src/config/config_service.py` exists with ui. and weights. in OPS_PREFIXES
- [x] `production/migrations/142_phase130_apr_seeds.sql` exists and applied
- [x] Commit db09d243 exists (Task 1)
- [x] Commit 58a60134 exists (Task 2)
- [x] 22 rows in config_state verified
