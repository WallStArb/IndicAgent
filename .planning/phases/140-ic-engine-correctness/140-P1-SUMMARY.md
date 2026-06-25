# Phase 140 P1 Summary — Migration 171

**Status:** Complete  
**Date:** 2026-06-25  
**Migration file:** `production/migrations/171_ic_correctness.sql`

## Changes Applied

### 1. feature_ic_scores.cluster_id column
- Added `cluster_id SMALLINT NULL` to `feature_ic_scores`
- NULL for all pre-Phase-140 rows (idempotent via `ADD COLUMN IF NOT EXISTS`)
- Comment records semantics: representative = highest |ic_value| in cluster; non-representatives get passes_fdr=false

### 2. APR key: alpha.ensemble.meta_fdr_min_fraction
- Seeded in config_schema and config_state with value `0.50`
- Consumed by ensemble_trainer.py (Phase 140 P3) to gate features on breadth of FDR passage across 232 (symbol, tf) cells
- ON CONFLICT DO NOTHING (idempotent)

### 3. APR key: alpha.ic.cluster_max_corr
- Seeded in config_schema and config_state with value `0.70`
- Consumed by ic_engine.py (Phase 140 P2) as dendrogram distance cutoff for scipy fcluster()
- ON CONFLICT DO NOTHING (idempotent)

### 4. alpha.ic.sharpe_min_windows: 10 → 30
- UPDATE applied; version incremented to 2
- Manual config_history row inserted (no trigger on config_state)
- Rationale: SE drops from ~0.32 (N=10) to ~0.18 (N=30), making the Sharpe gate a meaningful reliability filter

## Verification Results

```
feature_ic_scores.cluster_id: smallint NULL  OK
alpha.ensemble.meta_fdr_min_fraction | 0.50  OK
alpha.ic.cluster_max_corr            | 0.70  OK
alpha.ic.sharpe_min_windows          | 30    OK
```

## Commit
`a1172482` — feat(140-P1): migration 171 — cluster_id column, meta_fdr APR keys, sharpe_min_windows=30
