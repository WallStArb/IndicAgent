---
card_id: legacy-range-pct-fast-xs-ls-h5
kind: legacy_verdict
title: range_pct_fast cross-sectional long-short, 5-day hold (pooled 231-symbol universe)
idea: "A dollar-neutral long-short book ranked on range_pct_fast earns a personal-scale net edge that is not a market-beta tilt."
verdict: DEAD
verdict_date: 2026-09-02
recipe:
  spec: docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  script: scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py
  recipe_commit: 8f0bd464bb3e02e78b95e53d02520aba96f15fe4
results:
  - name: corrected_net_cheapest_corner_ci_bp
    value: "[-5.02, +8.59], mean +1.85 bp per rebalance (all 9 cost combinations fail CI > 0)"
    source: db:concept_registry
  - name: corrected_subperiod_net_bp
    value: "-3.87, -6.42, +14.16 (2 of 3 subperiods negative; stability fails)"
    source: db:concept_registry
  - name: shuffled_null_p
    value: 0.001
    source: db:concept_registry
  - name: beta_vs_equal_weight_universe
    value: "OLS beta +1.1368, R-squared 0.747"
    source: db:concept_registry
  - name: gross_mean_bp_per_rebalance
    value: "22.5, gross CI [9.2, 35.1] bp, 931 rebalances, mean turnover 0.451 per rebalance"
    source: db:concept_registry
  - name: per_symbol_bh_fdr
    value: "52/231 symbols pass"
    source: db:concept_registry
  - name: intercept_bp_per_rebalance
    value: 4.87
    source: db:concept_registry
  - name: verdict_change_from_correction
    value: "none: DEAD before and after the 2026-09-13 spread-constant correction"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "2026-09-13: the falsification script's live spread anchor carried a 10x transcription bug (0.0014, 14 bp, instead of 0.00014, 1.4 bp), the same bug personal_edge_paper_screen.py had already fixed in itself and never propagated here. It went undetected for 11 days through an AGY design review and the 2026-09-11 graveyard reconsideration."
  - "Originally recorded (wrong-anchor) numbers: net cheapest-corner CI [-7.9, +5.8] bp, subperiods -9.7, -12.1, +8.7 bp. The results above are the corrected ones; the originals are kept here and in concept_registry metadata (original_net_cheapest_corner_ci_bp, original_subperiod_net_bp)."
  - "The correction did not touch gross mean, beta, R-squared, shuffled-null p or turnover; point estimates moved favorably throughout and the qualitative verdict did not change."
  - "Ledger 2026-09-11 reconsideration recorded the beta-neutralized residual as the test actually performed; the reopened form (section 2) instead residualizes the target (S1) and drops the 3-of-3 stability gate."
spans_looked_at:
  - {start: 2007-08-14, end: 2025-12-23, role: in_sample}
forward_span_looks: 0
tables: [feature_vectors, forward_returns, concept_registry]
status_now: reopened
reopened_as: "construction-verdict-ledger.md section 2: cross-sectional family on S1 residual targets (range_pct_fast, both forms)"
reproducible: false
sources:
  - docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  - production/migrations/329_concept_registry_construction_domain.sql
  - production/migrations/335_concept_registry_range_pct_fast_pooled_spread_bug_correction.sql
  - db:concept_registry
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-range-pct-fast-xs-ls-h5-single-name-only]
---

# range_pct_fast cross-sectional long-short, 5-day hold (pooled 231-symbol universe)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `range_pct_fast_xs_ls_h5`; migrations 329 and 335

## What was tried

Pre-registration 1 of the personal-scale edge program: a dollar-neutral cross-sectional long-short
book on `feature_vectors.range_pct_fast`, decile-ranked daily, 5-day hold with stride 5 (offset 0
primary, offsets 1 to 4 ungated robustness), on the 231-symbol universe, in-sample only
(`bar_ts < alpha.validation.oos_start`). Nine cost combinations, a shuffled-ranking null, OLS
beta against the equal-weight universe mean, and a 3-subperiod stability check. The design was
locked, amended once after an AGY review, before the script ran.

## What was found

There is a real signal (shuffled-null p 0.001; gross mean 22.5 bp per rebalance with gross CI
[9.2, 35.1]) but it is a beta bet: OLS beta +1.14 with R-squared 0.75 against the equal-weight
universe mean, so it is not market-neutral alpha. Net of cost, all nine cost combinations fail
CI > 0 (corrected cheapest-corner CI [-5.02, +8.59] bp), and stability fails on the same shape,
two of three subperiods negative (-3.87, -6.42, +14.16 bp).

## Known defects

See front matter. The original 2026-09-02 run used a 10x too large spread constant; the
2026-09-13 rerun at the corrected anchor kept the DEAD verdict.

## Why closed

The ledger froze it DEAD (a market-beta tilt, not a personal-scale edge), verdict unchanged by
the correction, and the 2026-09-11 reconsideration confirmed it settled. It is reopened in ledger
section 2 (owner decision 2026-09-25) as a cross-sectional family on S1 residual targets, because
S1 residualizes the target (the failure mechanism) and the 3-of-3 stability gate is removed under
E15. This card stays a closed-verdict record; the reopening is a new pre-registered family
member disclosed as seen data. It cannot be rerun as-is: the script is deleted by 186-16,
`feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

Corrected numbers come from the `concept_registry` row for `range_pct_fast_xs_ls_h5`
(`domain = 'construction'`, `status = 'deprecated'`), whose metadata was updated by migration 335;
the original numbers are in the same row's `original_*` keys and in the ledger row. Read-only SQL,
run 2026-09-29:

```sql
SELECT name, status, added_phase, created_at, metadata FROM concept_registry
WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;
```

No script was rerun. `recipe_commit` is `git log -1 --format=%H --before="2026-09-13 23:59:59" --
scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py`, the 2026-09-13 spread-cost fix, so
the pointer names the corrected script (the original run used commit `0c9a344dd`, in the
metadata). `tables` come from the script's `FROM feature_vectors` and `JOIN forward_returns`,
plus `concept_registry` as the verdict store.

The span is inferred: the script filters `bar_ts < alpha.validation.oos_start`, and the start
(2007-08-14) and end (2025-12-23) are the outer edges of the three subperiod windows recorded for
this construction's single-name successor (migration 334), consistent with 931 five-session
rebalances. `forward_span_looks` is 0: the run was in-sample only.
