---
card_id: legacy-range-pct-fast-xs-ls-h5-single-name-only
kind: legacy_verdict
title: range_pct_fast cross-sectional long-short restricted to single-name equities (Pre-registration 3)
idea: "The range_pct_fast long-short book keeps a stable net edge when restricted to the 128 single-name equities, where the pooled verdict's beta contamination was smaller."
verdict: DEAD
verdict_date: 2026-09-13
recipe:
  spec: docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  script: scripts/analysis/range_pct_fast_beta_by_universe_composition.py
  recipe_commit: 9adf3f2d48d1ff6f3feb445bfa228122fe6594f8
results:
  - name: subperiod_net_bp_at_anchor_cost
    value: "+17.87, -1.14, +4.87 (windows 2007-08-14 to 2013-09-25, 2013-10-02 to 2019-11-06, 2019-11-13 to 2025-12-23)"
    source: db:concept_registry
  - name: failing_criterion
    value: "criterion (c), stability: net > 0 in 3 of 3 subperiods; fails on subperiod 2 alone (-1.14 bp)"
    source: db:concept_registry
  - name: single_name_vs_etf_only_beta
    value: "single-name beta 0.91 and R-squared 0.44; ETF-only beta 1.31 and R-squared 0.82"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: universe
    value: "single_name_equity tag, 128 of 231 symbols"
    source: db:concept_registry
  - name: preliminary_diagnostic_headline
    value: "primary-phase-only intercept 10.17 bp, which masked crisis-era concentration"
    source: db:concept_registry
  - name: criteria_a_b
    value: "not computed: all three criteria are required and (c) already fails under the locked design"
    source: db:concept_registry
known_defects:
  - "The AGY review's specific subperiod numbers (10.98, -8.26, -2.1 bp) were independently checked and found wrong. The qualitative call (criterion (c) fails) held; the verified numbers are +17.87, -1.14, +4.87 bp."
  - "The preliminary diagnostic's headline 10.17 bp (primary phase only) masked the instability: excess return is concentrated in the 2007-2013 crisis era, not uniform."
  - "AGY raised structural objections that were recorded and not resolved, moot for this verdict: meta-FDR adjustment for post-hoc subgroup selection, single-stock cost realism (spread and borrow), shuffled-null breaking sector-clustering exchangeability, survivorship (128 of 128 active), under-diversified K=6 legs in 2007-2008, and an unlocked unversioned symbol query."
  - "No separate falsification script was committed, since criterion (c) alone was decisive; the subperiod formula was verified directly. recipe.script names the composition diagnostic that motivated the restriction (concept_registry metadata and todo 375)."
  - "The AGY review document is not separately archived; its findings are folded into the concept_registry row and the ledger."
spans_looked_at:
  - {start: 2007-08-14, end: 2025-12-23, role: in_sample}
forward_span_looks: 0
tables: [feature_vectors, forward_returns, instrument_tags, concept_registry]
status_now: reopened
reopened_as: "construction-verdict-ledger.md section 2: cross-sectional family on S1 residual targets (range_pct_fast, both forms)"
reproducible: false
sources:
  - docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  - production/migrations/334_concept_registry_range_pct_fast_single_name_verdict.sql
  - .planning/todos/completed/375-single-name-only-range-pct-fast-refalsification.md
  - db:concept_registry
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-range-pct-fast-xs-ls-h5]
---

# range_pct_fast cross-sectional long-short restricted to single-name equities (Pre-registration 3)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `range_pct_fast_xs_ls_h5_single_name_only`; `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` (Pre-registration 3); migration 334; todo 375

## What was tried

A successor to the pooled `range_pct_fast_xs_ls_h5` verdict. A composition diagnostic
(`range_pct_fast_beta_by_universe_composition.py`) found the pooled beta contamination was
mostly an ETF-subset property (single-name beta 0.91 with R-squared 0.44 against ETF-only 1.31
and 0.82). Pre-registration 3 restricted the book to the 128 single-name equities, was AGY
reviewed before running, and pinned three PASS criteria including (c): net return above zero in
all three subperiods.

## What was found

Criterion (c) fails. The verified subperiod net returns at anchor cost are +17.87, -1.14 and
+4.87 bp; subperiod 2 (2013-10-02 to 2019-11-06) is negative. Under the pre-registration's
no-post-hoc-loosening clause this is DEAD on (c) alone, without the bootstrap CI and shuffled
null machinery. The preliminary diagnostic's 10.17 bp headline was primary-phase-only and hid
that the excess return sits in the 2007 to 2013 crisis era.

## Known defects

See front matter. AGY's specific subperiod numbers were wrong and the objections it raised were
recorded but not resolved.

## Why closed

The ledger froze it DEAD on the stability criterion. It is reopened in ledger section 2 (owner
decision 2026-09-25) with the pooled form: a cross-sectional family on S1 residual targets, since
S1 residualizes the target and the 3-of-3 stability gate is removed under E15. This card stays the
closed-verdict record. It cannot be rerun as-is: the recipe script is deleted by 186-16,
`feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

Subperiod, universe and diagnostic numbers come from the `concept_registry` row for
`range_pct_fast_xs_ls_h5_single_name_only` (`domain = 'construction'`, `status = 'deprecated'`,
migration 334); beta and R-squared come from the ledger row. Read-only SQL, run 2026-09-29:

```sql
SELECT name, status, added_phase, created_at, metadata FROM concept_registry
WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;
```

No script was rerun. The plan named `range_pct_fast_beta_by_universe_composition.py` "as named by
migration 334 and todo 375", so that is `recipe.script`. `recipe_commit` is `git log -1
--format=%H --before="2026-09-13 23:59:59" -- scripts/analysis/range_pct_fast_beta_by_universe_composition.py`.
`tables` come from the script's `FROM feature_vectors`, `JOIN forward_returns` and `FROM
instrument_tags`, plus `concept_registry` as the verdict store.

The span is the outer edge of the three recorded subperiod windows. `forward_span_looks` is 0:
the script reads `alpha.validation.oos_start` and the windows end 2025-12-23.
