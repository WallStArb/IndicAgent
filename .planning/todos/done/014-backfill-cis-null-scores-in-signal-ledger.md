---
created: 2026-03-26T22:38:31.852Z
updated: 2026-03-28T00:00:00.000Z
title: Backfill CIS null scores in signal_ledger
area: database
priority: 14
tier: data-gated
files:
  - src/intelligence/schemas.py
  - src/core/database_manager.py
---

## Problem

`signal_ledger` has 488,739 rows where `raw_cis_score`, `filtered_cis_score`, and `calibrated_confidence` are all NULL. These columns were added in Phase 35 but historical rows were never back-filled. New rows written by the current pipeline will have these populated correctly.

The NULL gap means `signal_ledger` cannot be used as a training dataset for v2.3 ML Foundation — any JOIN to get CIS features returns nothing.

A repair script was attempted but blocked: a single-pass JOIN across `signal_ledger` and `intelligence_features` (1.8M+ rows) exhausts PostgreSQL shared memory.

## Solution

Chunked back-fill approach:
- Process in batches by `(symbol, timeframe, date)` to keep JOIN size manageable
- Tune `work_mem` per session: `SET work_mem = '256MB'` before each batch
- JOIN key: `signal_ledger.symbol = intelligence_features.symbol AND signal_ledger.feature_ts = intelligence_features.ts AND signal_ledger.feature_tf = intelligence_features.tf`
- Source columns in `intelligence_features`: check `i7` JSONB for `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence`

Script location when created: `production/scripts/repair_cis_nulls.py`

**Priority**: Deferred — not urgent until v2.3 ML training pipeline is ready (needs 30+ days clean forward data first anyway). Do this as v2.3 prep work.

## Related

- Deferred from Phase 49 (DB Performance & Signal Ledger Hardening)
- Todo #005: Signal quality and pipeline integrity audit — broader ML training data gap audit
- REQUIREMENTS.md DATA-01 is marked `[x]` but is NOT done — update when this is complete
