---
card_id: legacy-todo304-percentile-rank-regimes
kind: legacy_verdict
title: Todo 304 per-symbol percentile-rank regimes (volatility_pct, skew_tail, volume_pct)
idea: "A per-symbol percentile rank of volatility, skew or volume sharpens momentum IC beyond what the HMM-derived regime_volatility already provides."
verdict: DEAD
verdict_date: 2026-09-01
recipe:
  spec: docs/research/measurement-per-symbol-percentile-rank-candidates.md
  script: scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py
  recipe_commit: 1084a1d1152532adc1339e577f7fcb59a60c517a
results:
  - name: stage2_volatility_pct_orthogonality
    value: "mean abs pearson_r 0.208, max 0.310 against regime_volatility (nominally over the 0.3 threshold; the candidate was exempt from Gate 1 by the design table)"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-2-orthogonality-run-2026-09-01
  - name: stage2_skew_tail_orthogonality
    value: "mean abs pearson_r 0.078, max 0.157"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-2-orthogonality-run-2026-09-01
  - name: stage2_volume_pct_orthogonality
    value: "mean abs pearson_r 0.075, max 0.171"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-2-orthogonality-run-2026-09-01
  - name: volatility_pct_momentum_z_fast_5m
    value: "uplift +40.9%, null_p 0.050, BH-FDR bh_p 0.475, fail (FDR)"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volatility_pct_momentum_z_mid_5m
    value: "uplift +47.7%, null_p 0.570, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: skew_tail_momentum_z_fast_5m
    value: "uplift +23.1%, null_p 0.545, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: skew_tail_momentum_z_mid_5m
    value: "uplift +67.0%, null_p 0.095, bh_p 0.475, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volume_pct_momentum_z_fast_5m
    value: "uplift +25.5%, null_p 0.885, bh_p 1.000, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volume_pct_momentum_z_mid_5m
    value: "uplift +74.2%, null_p 0.290, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volatility_pct_momentum_z_fast_15m
    value: "uplift +43.3%, null_p 0.655, bh_p 0.873, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volatility_pct_momentum_z_mid_15m
    value: "uplift +175.7%, null_p 0.425, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: skew_tail_momentum_z_fast_15m
    value: "uplift +55.8%, null_p 0.560, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: skew_tail_momentum_z_mid_15m
    value: "uplift +204.5%, null_p 0.345, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volume_pct_momentum_z_fast_15m
    value: "uplift +104.6%, null_p 0.200, bh_p 0.717, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: volume_pct_momentum_z_mid_15m
    value: "uplift +238.2%, null_p 0.395, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-percentile-rank-candidates.md#result-stage-3-falsification-null-arm-run-2026-09-01
known_defects:
  - "volatility_pct's Stage 2 max pearson_r of 0.310 is nominally over the 0.3 orthogonality threshold; it proceeded because the design table exempted it from Gate 1."
  - "Stage 2 orthogonality used 5 sample symbols, of which only 3 had non-empty regime_volatility."
  - "The 15m uplifts of up to +238.2% are a small-cell Sharpe artifact; every one has a null_p indistinguishable from chance (0.2 to 0.66)."
  - "The Stage 3 run is shared with todo 303 (one run, 20 tests pooled for BH-FDR); its forward-span look is counted on legacy-todo303-per-symbol-trend-regime."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-08-12, role: full_history}
forward_span_looks: 0
tables: [feature_vectors, forward_returns, market_data_ohlcv_tradeable]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-per-symbol-percentile-rank-candidates.md
  - .planning/todos/completed/304-per-symbol-percentile-rank-candidates-volume-skew-volatility.md
  - scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-todo303-per-symbol-trend-regime]
---

# Todo 304 per-symbol percentile-rank regimes (volatility_pct, skew_tail, volume_pct)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row Todo 304; `docs/research/measurement-per-symbol-percentile-rank-candidates.md`

## What was tried

Three causal per-symbol percentile ranks as candidate regime axes: `volatility_pct`, `skew_tail`
and `volume_pct`. Stage 1 validated the mechanism (15 of 15 causality checks pass, rank standard
deviation 0.284 to 0.294 against the uniform 0.289). Stage 2 checked orthogonality to
`regime_volatility`. Stage 3 ran the same day-clustered walk-forward Sharpe-uplift test as todo
303, with a 200-replicate null-arm control and BH-FDR across the 20 pooled tests. `volatility_pct`
doubled as a simplification test: does a plain percentile rank match the HMM's separation at
equal or lower complexity?

## What was found

None of the 12 cells clears the null-arm bar convincingly enough to survive BH-FDR. The best raw
null_p is 0.05 (`volatility_pct` with `momentum_z_fast` at 5m) and it fails at bh_p 0.475. None
of the three sharpens IC beyond `regime_volatility`, and `volatility_pct` shows no simplification
win either.

## Known defects

See front matter. The failing criterion is the standing null-arm (scrambled-data) control the
project requires of every regime candidate, plus BH-FDR across the pooled family.

## Why closed

The ledger froze it DEAD, closed, with none sharpening IC beyond the already-live
`regime_volatility`. It cannot be rerun as-is: the recipe scripts are deleted by 186-16,
`feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

Every number is copied from the Stage 2 and Stage 3 result sections of
`docs/research/measurement-per-symbol-percentile-rank-candidates.md`. No query was run and no
script was rerun.

The plan named `per_symbol_regime_candidates_stage3_falsification.py` for this card and the doc
agrees; it is the same script and the same run as the todo 303 card. `recipe_commit` is
`git log -1 --format=%H --before="2026-09-01 23:59:59" -- scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py`.
The span start follows the 186-01 corpus start convention and the end (2026-08-12) is the last
date ingestion delivered bars per the statistical factor residual doc. `forward_span_looks` is 0
on this card because the shared Stage 3 run read data at or after 2025-12-24 once, and that look
is counted on the todo 303 card.
