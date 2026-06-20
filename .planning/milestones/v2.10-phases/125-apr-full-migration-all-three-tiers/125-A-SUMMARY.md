---
phase: 125-apr-full-migration-all-three-tiers
plan: A
subsystem: database
tags: [postgres, timescaledb, config_state, parameter-store, apr, migration]

# Dependency graph
requires:
  - phase: 124-signal-universe-integrity-cold-start-hardening
    provides: migration 131 as baseline; config_schema/config_state/config_history tables exist

provides:
  - 10 new APR keys seeded in config_schema + config_state + config_history via migration 132
  - threshold.cis.fire_threshold / bucket_agree_min / bucket_noise_floor
  - feature.zone_engine.min_zone_width_atr (default + equity_etf/forex/futures variants)
  - weights.vwap_reversion.sigma_magnitude / hurst_quality / vol_stability

affects:
  - 125-B (reads CIS gate constants via ConfigService.get_sync)
  - 125-D (reads VWAP reversion weights via ConfigService.get_sync)
  - 125-E (reads CIS gate constants via ConfigService.get_sync)
  - 126-signal-universe-hardening (reads zone_width_atr keys once consumption code ships)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Triple-insert migration pattern: config_schema + config_state + config_history in one file"
    - "ON CONFLICT (config_key) DO NOTHING for idempotent migrations"
    - "changed_by = 'migration_NNN' in config_history for audit trail"

key-files:
  created:
    - production/migrations/132_phase125_param_store.sql
  modified: []

key-decisions:
  - "Zone-width keys seeded now as Phase 126 contract; consumption code ships in Phase 126 (not Phase 125)"
  - "config_history is append-only - second run of idempotent migration adds 10 more history rows (correct behavior)"
  - "ConfigService requires database_url positional arg - verified with postgresql://postgres:postgres@localhost:5432/indicagent"

patterns-established:
  - "min_zone_width_atr keys are distinct from min_width_atr (0.25) - different key, different purpose"
  - "Asset-class variant keys use dot-suffix notation: feature.zone_engine.min_zone_width_atr.equity_etf"

requirements-completed:
  - APR-01
  - APR-02

# Metrics
duration: 8min
completed: 2026-06-15
---

# Phase 125 Plan A: APR Migration - 10 new config keys via migration 132

**10 APR keys seeded across 3 clusters (CIS gates, zone width, VWAP weights) via idempotent triple-insert migration 132**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-15T08:43:00Z
- **Completed:** 2026-06-15T08:51:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Migration 132 created and applied: 10 new keys across config_schema, config_state, and config_history
- All 10 ConfigService.get_sync() calls return correct typed values without error
- Idempotency verified: second run inserts 0 rows into config_schema and config_state
- Existing feature.zone_engine.min_width_atr (0.25) confirmed unmodified

## Task Commits

1. **Task 1: Write migration 132 with 10 new APR keys** - `82547a19` (feat)

## Files Created/Modified

- `production/migrations/132_phase125_param_store.sql` - Triple-insert for 10 APR keys; applied to live DB

## Decisions Made

- Zone-width keys seeded now (Phase 126 contract) but consumption code ships in Phase 126 - no behavior change today
- config_history intentionally append-only; second idempotency run adds 10 more rows, which is correct

## Deviations from Plan

None - plan executed exactly as written. The ConfigService instantiation required `database_url` positional arg (not discovered in plan), handled inline without scope change.

## Issues Encountered

None.

## User Setup Required

None - migration applied directly to live DB.

## Next Phase Readiness

- Plans B, D, and E can now read all seeded keys via ConfigService.get_sync()
- Phase 126 zone-width consumption code has all 4 required keys (default + 3 asset-class variants) available
- Verified: min_zone_width_atr keys are distinct from existing min_width_atr key

## Self-Check

- [x] `production/migrations/132_phase125_param_store.sql` exists
- [x] Commit `82547a19` verified in git log
- [x] 10 rows in config_state confirmed via psql
- [x] 10 rows in config_history with changed_by = 'migration_132'
- [x] ConfigService.get_sync returns correct values for all 10 keys

## Self-Check: PASSED

---
*Phase: 125-apr-full-migration-all-three-tiers*
*Completed: 2026-06-15*
