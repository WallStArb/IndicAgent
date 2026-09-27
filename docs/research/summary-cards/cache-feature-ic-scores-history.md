---
card_id: cache-feature-ic-scores-history
kind: dead_cache
title: "Dead cache: feature_ic_scores_history"
idea: Append-only per-run IC scoring history for every feature column, written by the legacy ic_engine on each scoring pass.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: services/ic_engine.py
  recipe_commit: ea41a2d81096ec8a51730cac68026cadc03bfd00
results: []
known_defects:
  - No primary key (deduplication relied on insert discipline, not constraints).
  - 0 of 2 chunks compressed; the 38 GB body is almost entirely uncompressed heap.
spans_looked_at: []
forward_span_looks: 0
tables: [feature_ic_scores_history]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - services/ic_engine.py
  - db:feature_ic_scores_history
related_cards: [cache-feature-ic-scores-v1]
---

# Dead cache: feature_ic_scores_history

## What was tried

`feature_ic_scores_history` accumulated per-run IC scores for feature columns across the
legacy ic_engine's scoring passes, as the history layer behind the old feature lifecycle.

## What was found

The cache held 49,568,124 rows, about 38 GB, at the 2026-09-27 read. It is derived data:
recomputable from raw bars plus the scoring code, holding no conclusion that the verdict
ledger and summary cards do not already record. The current research pipeline (ic_engine
corpus runs) writes its own ledger, not this table.

## Known defects

No PK; 0/2 chunks compressed, so the 38 GB sits as uncompressed heap; any rebuild should not
inherit either property.

## Why closed

Pure derived cache superseded by the phase 183+ research ledger; dropped by phase 186 once
this card covers it.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM feature_ic_scores_history;  -- 49568124
```

The 38 GB size, no-PK and 0/2-compressed-chunk facts are the recorded values from
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-RESEARCH.md`.
