---
created: 2026-02-24T20:43:27.820Z
title: Add i7 JSONB column to intelligence_features
area: database
files:
  - production/migrations/009_intelligence_features.sql
  - src/intelligence/schemas.py:370-394
  - services/feature_writer_service.py
  - services/signal_generator_service.py
---

## Problem

`intelligence_features` stores I1–I6 per bar but has no `i7` column. This means the feature store cannot answer "which setups fired on this bar?" without joining to `signal_ledger` — and `signal_ledger` is an operational trading log (signal lifecycle, P&L outcomes), not a feature store. The gap breaks ML training queries that need to know what setups were active at each bar without pulling in operational columns.

## Solution

Add `i7 JSONB NOT NULL DEFAULT '{}'` column to `intelligence_features` with a GIN index. Populate it with which setups fired and their scores/confidence/direction — **not** lifecycle data (that stays in `signal_ledger`).

Use the **enrichment stream pattern** (Option B from analysis doc): signal_generator publishes i7 data to a separate `intelligence_i7:SYMBOL:TF` stream; feature_writer gains a second consumer group and UPSERTs `i7` column. This avoids circular stream dependencies (signal_generator is downstream of `intelligence:` stream).

See full design: `.planning/analysis/2026-02-24-feature-store-completeness.md`
