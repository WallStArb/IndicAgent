---
card_id: legacy-n1-nonlinear-interaction-combiner
kind: legacy_verdict
title: N1 residual-form nonlinear interaction combiner (LightGBM on the linear ensemble's residual)
idea: "A gradient-boosted tree fit on the linear ensemble's residual adds cross-sectional IC beyond the capped linear ensemble alone."
verdict: INCONCLUSIVE
verdict_date: 2026-08-25
recipe:
  spec: docs/research/measurement-nonlinear-interaction-combiner.md
  script: scripts/analysis/nonlinear_interaction_combiner_n1_verdict.py
  recipe_commit: f0d363f901b1eba2594ca737131818bb175ed3dd
results:
  - name: n1_1d_g1_breaches
    value: "G1 (15% gain concentration cap) breached on 5 of 5 folds in both arms; N1-a max share 0.404, 0.343, 0.453, 0.543, 0.375; N1-b 0.401, 0.341, 0.467, 0.538, 0.324; the run is VOID by the pre-registered rule"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#n1-result-2026-08-25-g1-void-at-1d-both-arms--stopped-before-the-expensive-15m1h-runs
  - name: n1_1d_point_estimates_void
    value: "N1-a point_diff -0.0018, ci_lower -0.0083, p 0.568; N1-b point_diff -0.0014, ci_lower -0.0076, p 0.648 (recorded for completeness, not evidence)"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#n1-result-2026-08-25-g1-void-at-1d-both-arms--stopped-before-the-expensive-15m1h-runs
  - name: n1_a_capped_1d
    value: "colsample_bytree 0.10: 2 marginal G1 breaches (15.3%, 15.9%, both f44); point_diff -0.0011, ci_lower -0.0080, p 0.760"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#test-n1-a-capped-pre-registered-2026-08-25-before-any-run-bounded-exposure-via-native-lightgbm-column-subsampling
  - name: n1_a_capped_1h_colsample_0_10
    value: "point_diff -0.0059, CI [-0.0082, -0.0037], p 0.0000 (composite significantly worse than linear); 1 of 5 folds breaches G1 (fold 1, gap_z, 0.248)"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#test-n1-a-capped-pre-registered-2026-08-25-before-any-run-bounded-exposure-via-native-lightgbm-column-subsampling
  - name: n1_a_capped_1h_colsample_0_05
    value: "point_diff -0.0012, CI [-0.0035, +0.0009], p 0.26; fold 1 still breaches G1 (gap_z 0.210)"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#test-n1-a-capped-pre-registered-2026-08-25-before-any-run-bounded-exposure-via-native-lightgbm-column-subsampling
  - name: rerun_2026_09_01_todo364
    value: "both 1h colsample arms reproduced bit-identically to the reported decimals on the same 6,646,123 rows; the instability is structural, not noise"
    source: docs/research/measurement-nonlinear-interaction-combiner.md#n1-a-capped--1h-fresh-re-run-2026-09-01-todo-364-both-colsample-values-reproduce-bit-identically--the-instability-is-confirmed-real-and-structural-not-measurement-noise
known_defects:
  - "Neither 1h colsample value cleared G1 on every fold (gap_z dominates fold 1 even at colsample 0.05), so no run at 1h is a fully clean read."
  - "The composite-versus-linear point estimate moves from -0.0059 (significantly worse) to -0.0012 (no effect) between two adjacent colsample_bytree values; neither number can be reported as the answer. The ledger instruction is not to cite it either way."
  - "The recommended next design (a per-feature gain cap or monotone_constraints) was never built; N1-a-capped was pre-registered as a one-off, and 15m and 5m were never run."
  - "The 1h corpus was frozen at 6,646,123 rows from 2026-08-12 (live ingestion down, todo 366), so the 09-01 rerun could not test staleness."
  - "Peak RSS reached 27 GB of a 29 GB host on the 09-01 reruns, near the module's OOM ceiling."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-08-12, role: full_history}
forward_span_looks: 5
tables: [feature_vectors, forward_returns, instruments, concept_registry]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-nonlinear-interaction-combiner.md
  - scripts/analysis/nonlinear_interaction_combiner_n1_test.py
  - scripts/analysis/_nonlinear_interaction_combiner_shared.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# N1 residual-form nonlinear interaction combiner (LightGBM on the linear ensemble's residual)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row N1 `nonlinear_interaction_combiner`; `docs/research/measurement-nonlinear-interaction-combiner.md`

## What was tried

Test N1 (pre-registered 2026-08-03): fit a LightGBM tree on the residual of the capped linear
ensemble and compare the composite's cross-sectional-neutral IC against the linear ensemble's
with a paired bootstrap. Guardrail G1 caps any one feature's share of total tree gain at 15%
per fold; a breach voids the run. N1-a and N1-b (with `interaction_constraints` from
`concept_registry.group_name`) ran at 1d first. The pre-registered follow-up N1-a-capped bounded
exposure with native LightGBM `colsample_bytree` and ran at 1d and 1h.

## What was found

The original unconstrained tree is the wrong instrument here: G1 breached on every fold in both
arms at 1d, with the same offending features (`poc_dist_atr`, `ctf_momentum`, `rsi_fast`). With
`colsample_bytree` capped, the 1h composite is significantly worse than linear at 0.10 (point
difference -0.0059, CI [-0.0082, -0.0037]) and indistinguishable at 0.05 (-0.0012, CI [-0.0035,
+0.0009]). The sign of significance flips between two adjacent, defensible settings at the
timeframe with the strongest prior evidence. A fresh rerun on 2026-09-01 reproduced both
bit-identically, so the instability is a property of the estimator, not measurement noise or
data drift.

## Known defects

See front matter. Under G4 (no post-hoc arms) the knob was not tuned further after two
disagreeing numbers.

## Why closed

The ledger froze it as structurally inconclusive: neither a pass nor a fail, and confirmed not
staleness. It says not to cite it as confirming or denying the thesis either way. It cannot be
rerun as-is: the recipe scripts are deleted by 186-16, `feature_vectors` is rebuilt, and E15
changed the gates. The idea is not reopened in ledger section 2.

## Where the numbers came from

Every number is copied from the N1 result, N1-a-capped and 2026-09-01 rerun sections of
`docs/research/measurement-nonlinear-interaction-combiner.md`. No query was run and no script
was rerun.

`recipe_commit` is `git log -1 --format=%H --before="2026-09-01 23:59:59" -- scripts/analysis/nonlinear_interaction_combiner_n1_verdict.py`;
the runner `nonlinear_interaction_combiner_n1_test.py` and the shared module are in `sources`.
`tables` come from the shared module's `FROM feature_vectors ... JOIN forward_returns ... JOIN
instruments` fetch, plus `concept_registry.group_name` read by the runner for N1-b.

The span start follows the 186-01 corpus start convention; the end (2026-08-12) is the last
date ingestion delivered bars, per the doc's own todo 366 note. `forward_span_looks` is 5: the
walk-forward folds span the full history including data at or after 2025-12-24, and five
distinct test statistics were produced (1d N1-a, 1d N1-b, 1d capped, 1h capped at 0.10, 1h
capped at 0.05). The 2026-09-01 reruns reproduced the same numbers on the same data and are not
counted as new looks. No other card counts these.
