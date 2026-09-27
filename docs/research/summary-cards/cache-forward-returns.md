---
card_id: cache-forward-returns
kind: dead_cache
title: "Dead cache: forward_returns"
idea: Precomputed forward return labels (return_fast/mid/slow/extended per bar) for IC measurement and gate evaluation across the old chain.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: services/forward_return_writer.py
  recipe_commit: 6a199857171d9a84a7ef80fc1eb2a7a8f7d8fc7e
results:
  - name: kernel_vs_table_horizon1
    value: "horizon 1 identical at 1d/5m/1h"
    source: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - name: kernel_vs_table_longer_1d_horizons
    value: "0.03-0.06% of rows differ, up to 0.11 log return"
    source: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - name: kernel_vs_table_5m
    value: "1.6-6.9% of rows differ; 467k extended rows exist only in the table"
    source: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - name: kernel_vs_table_1h
    value: "20/60-bar horizons exist only in the table"
    source: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - name: kernel_cost
    value: "kernel recomputes in ~5 s vs 61 s reading the table"
    source: .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
known_defects:
  - Coverage stops at 2025-12-23 for training-window rows and covers 233 of 932 names; 1,008 1d bars on 4 names have no row under the coverage map, so absence must never be read as zero return.
  - "The table is legacy (UD-25): new code computes targets with the kernel and never reads this table; panel.forward_returns is the one target definition."
  - "It also carried corrupt prints the volume>0 tradeable filter does not catch (see legacy-em-cal-emission-threshold: UUP 2007 $1000 print, 27 rows with abs(return_fast) > 0.5)."
spans_looked_at: []
forward_span_looks: 0
tables: [forward_returns]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - services/forward_return_writer.py
  - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - .planning/todos/completed/253-forward-returns-frozen-at-oos-boundary-corpus-rebuild-skipped-step3.md
  - docs/research/2026-07-30-forward-return-horizon-grid-refactor.md
  - db:forward_returns
related_cards: [legacy-phase148-oos-gates, legacy-em-cal-emission-threshold]
---

# Dead cache: forward_returns

## What was tried

`forward_return_writer.py` precomputed forward-return labels per (symbol, tf, bar, horizon)
so the old chain's IC engine and OOS gates could join them without recomputation.

## What was found

The table held 103,882,276 rows at the 2026-09-27 read, about 14 GB, covering 233 of 932
names, with training-side rows ending 2025-12-23 (the OOS boundary was only backfilled past
once, for the phase 148 Gate 1 run). The kernel-vs-table comparison in 186-CONTEXT shows the
kernel reproduces horizon 1 exactly and diverges from the table only where the table holds
rows the kernel does not generate (extended 5m rows, 1h 20/60 horizons) or on a small tail of
longer-horizon rows. Kernel recomputation costs about 5 s against 61 s to read the table, so
the cache buys nothing.

## Known defects

Partial universe and time coverage; absence of a row is not a zero return; corrupt prints
passed through; superseded by `panel.forward_returns` (UD-25).

## Why closed

Pure derived cache, cheaper to recompute than to store; dropped by phase 186 once this card
covers it, with the kernel comparison numbers preserved above.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM forward_returns;  -- 103882276
```

The kernel-vs-table numbers, coverage figures and kernel cost are copied verbatim from
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md`
("Specific ideas") and 186-RESEARCH.md "Tables".
