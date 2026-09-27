---
card_id: cache-feature-ic-scores-v1
kind: dead_cache
title: "Dead cache: feature_ic_scores (v1)"
idea: The legacy per-(feature, symbol, tf, regime, lookahead) IC score snapshot at the OOS boundary, consumed by the ensemble trainer's feature selection.
verdict: NO_CONCLUSION
verdict_date: 2026-09-27
recipe:
  spec: null
  script: services/ic_engine.py
  recipe_commit: ea41a2d81096ec8a51730cac68026cadc03bfd00
results:
  - name: rows
    value: 10616092
    source: db:feature_ic_scores
  - name: training_window_end_values
    value: "every row carries training_window_end = 2025-12-24 05:15:00+00 (alpha.validation.oos_start)"
    source: db:feature_ic_scores
  - name: scope_split_non_pooled
    value: "9314739 total: cross_sectional 5540805, earnings_season 2188440, symbol_hmm 1585494"
    source: db:feature_ic_scores
  - name: scope_split_pooled
    value: "1301353 total: pooled 971073, earnings_season pooled 210600, cross_sectional pooled 119680"
    source: db:feature_ic_scores
known_defects:
  - "Two-clock defect: the single training_window_end column carried oos_start for every legacy row, while fresh rows need the latest target exit bar as their clock; this is why 186-14 writes fresh rows to feature_ic_scores_v2 instead of this table."
  - The parity report from 186-20 is the replay record of these stored cells; this card preserves only the counts and the defect.
spans_looked_at: []
forward_span_looks: 0
tables: [feature_ic_scores]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - services/ic_engine.py
  - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md
  - db:feature_ic_scores
related_cards: [cache-feature-ic-scores-history]
---

# Dead cache: feature_ic_scores (v1)

## What was tried

The legacy ic_engine scored every feature column's IC per (symbol, tf, regime, lookahead)
against the training window ending at the OOS boundary and wrote the snapshot to
`feature_ic_scores`, which the ensemble trainer read for feature selection.

## What was found

The table held 10,616,092 rows at the 2026-09-27 read, every row stamped
`training_window_end = 2025-12-24 05:15:00+00`. Scope split: 9,314,739 non-pooled rows
(cross_sectional 5,540,805; earnings_season 2,188,440; symbol_hmm 1,585,494) and 1,301,353
pooled rows (per-symbol pooled 971,073; POOLED earnings_season 210,600; POOLED
cross_sectional 119,680). These are the cells the phase 186 rebuild must be able to replay;
the 186-20 parity report is that replay's record, and 186-28 drops this table whole once
this card covers it.

## Known defects

The two-clock defect above: one `training_window_end` column cannot serve both the frozen
legacy snapshot semantics and fresh rows keyed to the latest target exit bar, so fresh writes
go to `feature_ic_scores_v2` (186-14) rather than mutating this table.

## Why closed

Derived cache at a frozen clock; its content is preserved by the parity report and the v2
table, and the drop proceeds after this card plus the parity gate.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM feature_ic_scores;  -- 10616092
SELECT DISTINCT training_window_end FROM feature_ic_scores;  -- 2025-12-24 05:15:00+00
SELECT regime_scope, is_pooled, count(*) FROM feature_ic_scores GROUP BY 1, 2 ORDER BY 3 DESC;
```

The defect framing is quoted from
`.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md`.
