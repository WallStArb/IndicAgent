---
created: 2026-04-13T16:22:45.107Z
title: Rename legacy DB columns to match naming conventions (tf, ts)
area: database
files:
  - production/migrations/065_schema_optimizations.sql
  - src/core/stream_keys.py
---

## Problem

Several older tables use column names that predate the established `ts` / `tf` naming conventions documented in CLAUDE.md. Surfaced during 2026-04-13 schema audit:

| Table | Current | Should be |
|-------|---------|-----------|
| `market_data_ohlcv` | `timestamp` | `ts` |
| `market_data_ohlcv` | `timeframe` | `tf` |
| `signal_ledger` | `timeframe` | `tf` (`timestamp` stays — it's the hypertable PK) |
| `setup_performance` | `timeframe` | `tf` |
| `intelligence_metrics` | `timeframe` | `tf` |
| `intelligence_metrics` | `measured_at` | `ts` |
| `signal_metrics_dq_failures` | `created_at` | `ts` |

These are not currently causing bugs but create inconsistency. The convention `ts` / `tf` is enforced in all new tables and CLAUDE.md.

## Solution

Do as a dedicated low-risk-window phase. Each rename requires:
1. Migration: `ALTER TABLE ... RENAME COLUMN old TO new`
2. Update all service code that references the column (grep for each table+column pair)
3. Update any views built on the table (`market_data_5m` uses `market_data_ohlcv.timestamp` and `.timeframe`)
4. Update dashboard API routes that query these tables

`signal_ledger.timestamp` is the hypertable partitioning column — TimescaleDB allows renaming it but the hypertable metadata must be verified post-rename. Do this one last and test carefully.
