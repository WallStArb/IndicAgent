---
card_id: cache-context-features
kind: dead_cache
title: "Dead cache: context_features"
idea: Derived per-bar context features (GARCH, Kalman, VWAP, VIX-regime style annotations) persisted alongside the old chain.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: scripts/infrastructure/backfill/infrastructure_context_features_writer.py
  recipe_commit: 81718b9895c0f6fe98ba3ce965016dca6f2aa607
results: []
known_defects:
  - Written only by the backfill writer script; services/context_writer.py does not write this table (R-01), so its writer lineage is a single nightly-batch path.
  - Last write predates the current corpus; the cache holds no live consumer after the old chain retires.
spans_looked_at: []
forward_span_looks: 0
tables: [context_features]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - scripts/infrastructure/backfill/infrastructure_context_features_writer.py
  - db:context_features
related_cards: [cache-ctx-tables]
---

# Dead cache: context_features

## What was tried

`context_features` stored derived per-bar context features for the old chain, written by the
nightly backfill writer `scripts/infrastructure/backfill/infrastructure_context_features_writer.py`.

## What was found

The cache held 8,985 rows (1.6 MB total) as of the 2026-09-27 read. It is derived data in the
design 14.2 sense: rebuildable from raw bars, with no conclusion embedded in it. No research
verdict ever depended on it.

## Known defects

Not written by `context_writer.py` (R-01); a single batch writer path. No live consumer after
the old chain retires.

## Why closed

Pure derived cache with no learned content; dropped by phase 186 once this card covers it.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM context_features;  -- 8985
SELECT pg_size_pretty(pg_total_relation_size('context_features'));  -- 1616 kB (parent; chunk sizes per 186-RESEARCH.md: 1.6 MB)
```

Row count is live; the size figure is the recorded value from
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-RESEARCH.md`.
