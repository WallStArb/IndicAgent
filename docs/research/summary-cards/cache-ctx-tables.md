---
card_id: cache-ctx-tables
kind: dead_cache
title: "Dead cache: ctx_events and ctx_snapshots"
idea: Context snapshot events and snapshots for the old chain's context layer, persisted by context_writer from the ctx.snapshot topic.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: services/context_writer.py
  recipe_commit: b658ae690dce69fb301a4697482763c9a9150d92
results: []
known_defects:
  - The ctx.snapshot topic never had a publisher, so both tables were dead on arrival (R-01); the writer consumed a topic that nothing produced.
spans_looked_at: []
forward_span_looks: 0
tables: [ctx_events, ctx_snapshots]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - services/context_writer.py
  - db:ctx_events
  - db:ctx_snapshots
related_cards: [cache-context-features]
---

# Dead cache: ctx_events and ctx_snapshots

## What was tried

`context_writer.py` consumed the `ctx.snapshot` topic and persisted context events and
snapshots into `ctx_events` and `ctx_snapshots` for the old chain's context layer.

## What was found

Both tables hold 0 rows (2026-09-27 read). The topic never had a publisher (R-01), so the
pipeline was dead on arrival: a writer with no upstream. No data was ever cached, and no
conclusion could have been learned from it.

## Known defects

As in the front matter: no publisher ever existed for `ctx.snapshot`.

## Why closed

Empty caches with no history to preserve; dropped by phase 186 once this card covers both.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM ctx_events;  -- 0
SELECT count(*) FROM ctx_snapshots;  -- 0
```
