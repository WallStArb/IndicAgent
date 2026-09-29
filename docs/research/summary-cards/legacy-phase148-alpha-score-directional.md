---
card_id: legacy-phase148-alpha-score-directional
kind: legacy_verdict
title: Phase 148 alpha_score_directional placement against the personal cost hurdle (killed on paper)
idea: "The phase 148 per-symbol directional construction, whose Gate 1 passed, clears a personal-scale cost hurdle even though the institutional Gate 2 failed."
verdict: KILLED_ON_PAPER
verdict_date: 2026-09-02
recipe:
  spec: null
  script: scripts/analysis/phase148_personal_hurdle_placement.py
  recipe_commit: c3ad8116c358c6df8e227489400018c418c27d4f
results:
  - name: gate1_cells
    value: "140 of 640 OOS cells qualify (21.875%), 5m and 15m"
    source: db:concept_registry
  - name: gate2_mean_pnl_r_gross
    value: "-0.1215 (-0.1214896), 33892 frames over 69 OOS days, negative gross of any cost"
    source: db:concept_registry
  - name: gate2_sharpe_and_drawdown
    value: "Sharpe 0.3851; max drawdown ratio 9.596"
    source: db:concept_registry
  - name: unbiased_all_cell_mean_rank_ic
    value: "0.000 to 0.050 across the 8 (tf, scale) cells; 5m fast 0.0008, mid -0.0011, slow -0.0077, ext 0.0078; 15m fast 0.0, mid 0.0498, slow 0.0186, ext 0.0213"
    source: db:concept_registry
  - name: qualifying_cell_mean_rank_ic
    value: "selection-inflated: 5m 0.0311, 0.0446, 0.048, 0.0662; 15m mid 0.114, slow 0.1255, ext 0.1802 (15m fast has no qualifying cell)"
    source: db:concept_registry
  - name: sign_cofiring_across_cells
    value: "5m 99.6%, 15m 100.0%, 1h 100.0%, 1d 100.0% same-direction"
    source: db:concept_registry
  - name: personal_cost_band
    value: "spread band 0.7, 1.4, 2.8 bp; turnover band 0.08 to 0.45 per rebalance; 1 to 2 bets per rebalance; fails the personal hurdle on every cell under the worst-case band"
    source: db:concept_registry
  - name: todo277_pooled_ic_15m
    value: "raw -0.00129, residual +0.00453"
    source: db:concept_registry
known_defects:
  - "The 140-of-640 Gate 1 pass is selection-inflated: the cells were chosen from 640 by the same FDR procedure that claims significance. The unbiased all-cell mean rank-IC is 0.000 to 0.050."
  - "100% sign co-firing across cells means there was never independent breadth to refine (ledger, reconsidered 2026-09-11)."
  - "The 0c screen this placement supersedes had a 10x spread-constant transcription error (0.0014 for 0.00014) fixed the same day; margins were understated and no verdict flipped. The numbers here use the corrected 1.4 bp anchor."
  - "Gate 1 covered 5m and 15m only (ensemble_alpha had no OOS rows at 1h and 1d)."
spans_looked_at:
  - {start: 2025-12-24, end: 2026-07-23, role: forward_span}
forward_span_looks: 0
tables: [ensemble_alpha, forward_returns, alpha_frames, gate_evaluations, concept_registry]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - production/migrations/328_concept_registry_phase148_placement_verdict.sql
  - .planning/todos/completed/367-paper-placement-against-personal-hurdle.md
  - db:concept_registry
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-phase148-oos-gates, legacy-phase148-score-01-03, legacy-ensemble-champion]
---

# Phase 148 alpha_score_directional placement against the personal cost hurdle (killed on paper)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row Phase 148 `alpha_score_directional`; migration 328; todo 367

## What was tried

Workstream 0c of the personal-scale edge program (todo 367): place the phase 148 per-symbol
directional construction's already-measured signal mass against a personal cost hurdle
(spread 0.7, 1.4 and 2.8 bp, turnover 0.08 to 0.45, one to two bets per rebalance), rather than
the institutional-calibrated Gate 2 that had killed it. No new measurement run; the script reads
stored gate evidence and existing sign co-firing counts.

## What was found

Gate 1 passed (140 of 640 OOS cells) but the construction fails the personal hurdle on every
cell under the worst-case band. The decisive, band-independent result is Gate 2's realized OOS
frame P&L, negative gross of any cost (mean -0.1215R over 33,892 frames and 69 days); a lower
cost hurdle cannot rescue a negative gross edge. The unbiased all-cell mean rank-IC is 0.000 to
0.050, and 100% sign co-firing across cells shows no independent breadth.

## Known defects

See front matter. The construction was killed on paper, with no new trading test.

## Why closed

The ledger froze it killed on paper and the 2026-09-11 reconsideration confirmed it settled.
It cannot be rerun as-is: the script is deleted by 186-16, the old chain's tables
(`ensemble_alpha`, `alpha_frames`) are dropped under phase 186, and E15 removed the gate the
Gate 1 pass came from. The two forward-span gate looks themselves live on
`legacy-phase148-oos-gates`.

## Where the numbers came from

Numbers come from the `concept_registry` row for `phase148_alpha_score_directional`
(`domain = 'construction'`, `status = 'deprecated'`, migration 328). Read-only SQL, run 2026-09-29:

```sql
SELECT name, status, added_phase, created_at, metadata FROM concept_registry
WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;
```

The ledger row supplies the 0.000 to 0.050 range and the "worst-case band" statement; todo 367
records the workstream. No script was rerun. `recipe_commit` is `git log -1 --format=%H
--before="2026-09-02 23:59:59" -- scripts/analysis/phase148_personal_hurdle_placement.py`.
`tables` cover the placement's Gate 1 and Gate 2 inputs (`ensemble_alpha`, `forward_returns`,
`alpha_frames`) as recorded on the 186-01 gate cards, plus `gate_evaluations` (the script's own
`FROM`) and `concept_registry`.

`forward_span_looks` is 0 on this card: the two forward-span looks (Gate 1 on 2026-07-22 and
Gate 2 on 2026-07-23) are counted on `legacy-phase148-oos-gates`, and this placement only read
their stored outputs. The span is the same forward span those cards record.
