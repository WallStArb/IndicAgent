---
card_id: legacy-bars-since-high-fast-xs-ls-h5
kind: legacy_verdict
title: bars_since_high_fast cross-sectional long-short, 5-day hold (regime-gate reconsideration)
idea: "A regime-gated cross-sectional long-short on bars_since_high_fast earns a coherent edge, as its 0.11 average IC across 46 symbols suggests."
verdict: DEAD
verdict_date: 2026-09-11
recipe:
  spec: docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md
  script: scripts/analysis/personal_edge_paper_screen.py
  recipe_commit: c3ad8116c358c6df8e227489400018c418c27d4f
results:
  - name: unconditional_spread_mean_per_rebalance
    value: "-0.0004 (negative gross return)"
    source: db:concept_registry
  - name: unconditional_pooled_regime_avg_ic
    value: 0.1118
    source: db:concept_registry
  - name: unconditional_beta_and_r2
    value: "beta 0.19, R-squared 0.085 (rules out beta contamination)"
    source: db:concept_registry
  - name: regime_gate_premise
    value: "0.11 average IC across 46 of 187 symbols (from scripts/analysis/personal_edge_paper_screen.py, H=5)"
    source: db:concept_registry
  - name: standout_cell
    value: "commodity down_primary_backwardation: IC 0.299, p 2e-5, FDR-pass, on only 52 days across 16 years (2008-2024)"
    source: db:concept_registry
  - name: robust_cells_excluding_standout
    value: "equity mid_neutral IC 0.043 and high_bear IC 0.040 (n_independent about 24k each)"
    source: db:concept_registry
  - name: successor_sign_consistency_pct
    value: "51 to 58% for the SR-level-support divergence successor (sr_pivot_volume_divergence via _compute_sr_dist_atr)"
    source: db:concept_registry
known_defects:
  - "The unconditional spread check and the successor sign-consistency numbers were computed ad hoc. No pre-registered or committed falsification script exists in git history (concept_registry metadata: committed_falsification_script false; remediation todo 374). recipe.script names the screen that produced the 0.11 premise, not a script that produced the spread number."
  - "The regime-decomposition attribution is reproducible: pure SQL over persisted feature_ic_scores and market_regimes."
  - "The 0.11 average IC averaged FDR-passing cells drawn from four different regime taxonomies (equity trend x vol, commodity contango/backwardation, rates curve shape, fx dollar risk), so it does not describe one coherent hold-in-regime-X signal."
  - "The exact window of the ad hoc spread check is not recorded; the span below assumes the in-sample convention of feature_ic_scores (bar_ts before 2025-12-24)."
spans_looked_at:
  - {start: 2006-09-01, end: 2025-12-24, role: in_sample}
forward_span_looks: 0
tables: [feature_ic_scores, market_regimes, feature_vectors, forward_returns, concept_registry]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md
  - production/migrations/333_concept_registry_bars_since_high_fast_verdict.sql
  - db:concept_registry
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# bars_since_high_fast cross-sectional long-short, 5-day hold (regime-gate reconsideration)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `bars_since_high_fast_xs_ls_h5`; `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md` (graveyard item 4)

## What was tried

Graveyard reconsideration item 4 of the 2026-09-11 strategic-plans review: the paper screen
(`personal_edge_paper_screen.py`, H=5) showed `bars_since_high_fast` with about 0.11 average IC
and 46-symbol support, which suggested a regime-gated cross-sectional long-short. The
reconsideration ran an unconditional full-history spread check, decomposed the 0.11 by regime
taxonomy from `feature_ic_scores` and `market_regimes`, and tested a structural successor
(SR-level-support divergence).

## What was found

The unconditional spread has negative gross return (mean -0.0004 per rebalance) despite a
positive pooled regime-averaged IC of 0.1118, with low beta (0.19, R-squared 0.085). The 0.11
decomposes into five FDR-passing cells across four different regime taxonomies. The standout,
commodity `down_primary_backwardation` (IC 0.299, p 2e-5), sits on 52 days over 16 years: a
handful of macro-shock episodes, not 52 independent bets. Without it, only two broad equity
cells remain (IC 0.043 and 0.040), barely above the already-failed pooled IC. The successor is
flat at 51 to 58% sign consistency.

## Known defects

See front matter. The verdict rests on ad hoc computations for the spread and successor
numbers, with only the regime decomposition reproducible.

## Why closed

The ledger froze it DEAD: no untried regime-gate construction survives the decomposition, so
graveyard item 4 was closed on that basis, not merely as unreproduced. It cannot be rerun as-is:
the screen script is deleted by 186-16, `feature_vectors` and `feature_ic_scores` are rebuilt or
retired, and E15 changed the gates.

## Where the numbers came from

Numbers come from the `concept_registry` row for `bars_since_high_fast_xs_ls_h5`
(`domain = 'construction'`, `status = 'deprecated'`, migration 333, `created_at` 2026-09-12) and
match the ledger row. Read-only SQL, run 2026-09-29:

```sql
SELECT name, status, added_phase, created_at, metadata FROM concept_registry
WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;
```

No script was rerun. `recipe_commit` is `git log -1 --format=%H --before="2026-09-11 23:59:59"
-- scripts/analysis/personal_edge_paper_screen.py`. `tables` are the screen's `FROM
feature_ic_scores` plus the tables the ledger row and graveyard doc name for the spread check
and decomposition (`market_regimes`, `feature_vectors`, `forward_returns`) and `concept_registry`
as the verdict store.

`forward_span_looks` is 0: the analysis read persisted in-sample IC rows and an in-sample spread
panel, with no record of reading data at or after 2025-12-24.
