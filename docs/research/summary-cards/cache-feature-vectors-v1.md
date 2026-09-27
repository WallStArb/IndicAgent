---
card_id: cache-feature-vectors-v1
kind: dead_cache
title: "Dead cache: feature_vectors (v1)"
idea: The v1 per-bar feature matrix (rank-normalized feature columns per symbol/tf/bar) that fed ensemble training and IC measurement across the old chain.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: services/backfill_feature_factory.py
  recipe_commit: 5c7ecd7c9e1f2327a764eee7e60e7fe18d327fd4
results: []
known_defects:
  - 75.1M of its 108.6M rows are 5m, the timeframe no active family reads (TF-stack economics, todo 445); the rebuild re-decides the timeframe stack instead of copying it.
  - Its column set includes v2.x raw-price fields later shown to be invalid feature columns; the rebuild does not carry them forward.
spans_looked_at: []
forward_span_looks: 0
tables: [feature_vectors]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - services/backfill_feature_factory.py
  - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-RESEARCH.md
  - db:feature_vectors
related_cards: []
---

# Dead cache: feature_vectors (v1)

## What was tried

`backfill_feature_factory.py` built and maintained the v1 `feature_vectors` hypertable: the
per-bar feature matrix the ensemble trainer, ic_engine and all old-chain consumers read.

## What was found

The cache held 108,646,010 rows at the 2026-09-27 read: 89 GB compressed, 491 GB uncompressed,
over 233 names with 90-day chunks, of which 75.1M rows (about 69%) are 5m. It is the largest
single piece of derived data in the database and pure cache: the phase 186 rebuild
(186-24..186-27) replaces it, and the drift report comparing the rebuilt matrix to the stored
one lands with 186-27 before the drop.

## Known defects

5m-heavy composition with no active consumer; carries invalid v2.x raw-price columns; its
size drove the 768 GB disk-full incident class of risk on schema changes.

## Why closed

Derived cache; the rebuild supersedes it and the summary card preserves its shape (rows,
share by timeframe, names, chunk interval) so the drift report has a fixed reference.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM feature_vectors;  -- 108646010
```

Sizes, the 5m share, name count and chunk interval are the recorded values from
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-RESEARCH.md`
("Tables").
