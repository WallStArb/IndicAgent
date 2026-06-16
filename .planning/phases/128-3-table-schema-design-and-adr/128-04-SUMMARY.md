---
phase: 128-3-table-schema-design-and-adr
plan: "04"
subsystem: intelligence/trading
tags: [schema, ddl, signal-ledger, 3-table]
dependency_graph:
  requires: [128-01, 128-02, 128-03]
  provides: [schema_enrichment_columns]
  affects: [signal_events, trade_frames, trade_executions, signal_ledger_full]
tech_stack:
  added: []
  patterns: [additive-ddl, alter-table]
key_files:
  modified:
    - production/migrations/137_3table_schema.sql
    - docs/signals/signal-trade-separation-ADR.md
decisions:
  - "int2 for regime columns (codes 0-4) vs int4 for hmm_regime_at_fire — intentional, saves space"
  - "feature_ts nullable — backfill signals may predate intelligence_features rows"
  - "concurrent_* populated by SignalAggregator/RankerWriter from in-process state, not DB query"
metrics:
  duration_minutes: 10
  tasks_completed: 3
  tasks_total: 3
  files_changed: 2
  completed_date: "2026-06-16"
---

# Phase 128 Plan 04: Schema Enrichment — Feature Link, Regime Columns, Cross-Signal Context Summary

**One-liner:** Added 5 columns across signal_events / trade_frames / trade_executions via `ALTER TABLE IF NOT EXISTS` and refreshed the `signal_ledger_full` view to expose all new columns.

## Tasks Completed

| Task | Name | Files |
|------|------|-------|
| 1 | Add columns to 137_3table_schema.sql DDL | 137_3table_schema.sql |
| 2 | Apply ALTER TABLE to live DB + recreate view | DB (live) |
| 3 | Update ADR with new columns + Phase 130 writer contract | signal-trade-separation-ADR.md |

## Columns Added

### signal_events
| Column | Type | Purpose |
|--------|------|---------|
| `feature_ts` | `timestamptz` | JOIN anchor to `intelligence_features` row that generated this signal |
| `concurrent_signal_count` | `int2` | Count of other active signals at fire time (crowding indicator) |
| `concurrent_plugins` | `text[]` | `setup_plugin` values of concurrent active signals (ML-queryable) |

### trade_frames
| Column | Type | Purpose |
|--------|------|---------|
| `regime_at_activation` | `int2` | HMM regime at entry condition trigger; NULL for `at_close` |

### trade_executions
| Column | Type | Purpose |
|--------|------|---------|
| `regime_at_exit` | `int2` | HMM regime at position exit; enables regime-transition analysis |

## Verification

```sql
-- All 5 columns present in live DB
SELECT table_name, column_name FROM information_schema.columns
WHERE table_name IN ('signal_events','trade_frames','trade_executions')
  AND column_name IN ('feature_ts','concurrent_signal_count','concurrent_plugins',
                      'regime_at_activation','regime_at_exit');
-- 5 rows returned

-- View exposes all 5 columns
SELECT column_name FROM information_schema.columns
WHERE table_name = 'signal_ledger_full'
  AND column_name IN ('feature_ts','concurrent_signal_count','concurrent_plugins',
                      'regime_at_activation','regime_at_exit');
-- 5 rows returned
```

## Self-Check: PASSED

- All 5 columns in signal_events / trade_frames / trade_executions: CONFIRMED
- signal_ledger_full view exposes all 5: CONFIRMED
- migration SQL updated: CONFIRMED
- ADR updated with Phase 130 writer obligations: CONFIRMED
