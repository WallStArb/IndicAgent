---
card_id: legacy-todo303-per-symbol-trend-regime
kind: legacy_verdict
title: Todo 303 per-symbol trend regime candidates (hurst_rank, autocorr_rank)
idea: "A per-symbol percentile rank of Hurst exponent or lag-1 autocorrelation sharpens momentum IC beyond what regime_volatility already provides."
verdict: DEAD
verdict_date: 2026-09-01
recipe:
  spec: docs/research/measurement-per-symbol-trend-regime.md
  script: scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py
  recipe_commit: 1084a1d1152532adc1339e577f7fcb59a60c517a
results:
  - name: stage2_hurst_rank_orthogonality
    value: "mean abs pearson_r 0.040, max 0.061 against regime_volatility (n_symbols=3), below the 0.3 threshold"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-2-orthogonality-run-2026-09-01
  - name: stage2_autocorr_rank_orthogonality
    value: "mean abs pearson_r 0.100, max 0.202 against regime_volatility, below the 0.3 threshold"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-2-orthogonality-run-2026-09-01
  - name: hurst_rank_momentum_z_fast_5m
    value: "uplift +53.3%, null_p 0.030, BH-FDR bh_p 0.475, fail (FDR)"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: hurst_rank_momentum_z_mid_5m
    value: "uplift +35.5%, null_p 1.000, bh_p 1.000, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: autocorr_rank_momentum_z_fast_5m
    value: "uplift +37.0%, null_p 0.075, bh_p 0.475, fail (FDR)"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: autocorr_rank_momentum_z_mid_5m
    value: "uplift +35.1%, null_p 0.975, bh_p 1.000, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: hurst_rank_momentum_z_fast_15m
    value: "uplift +15.9%, null_p 1.000, bh_p 1.000, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: hurst_rank_momentum_z_mid_15m
    value: "uplift +141.5%, null_p 0.850, bh_p 1.000, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: autocorr_rank_momentum_z_fast_15m
    value: "uplift +60.9%, null_p 0.515, bh_p 0.814, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: autocorr_rank_momentum_z_mid_15m
    value: "uplift +223.7%, null_p 0.215, bh_p 0.717, fail"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
  - name: bh_fdr_family
    value: "20 threshold-clearing tests pooled across todos 303 and 304 (both timeframes, both x_bar columns); 200-replicate null arm"
    source: docs/research/measurement-per-symbol-trend-regime.md#result-stage-3-falsification-null-arm-run-2026-09-01
known_defects:
  - "The design's pass criterion of N above 20,000 bars was unreachable at the 5-symbol, 1d probe, so Stage 3 moved to 5m and 15m (never 1m); the doc records this as a correction to its own spec."
  - "Stage 2 orthogonality used 5 sample symbols, of which only 3 had non-empty regime_volatility."
  - "The large 15m uplifts (up to +223.7%) are a small-cell Sharpe artifact, not evidence; the null arm caught them."
  - "The 5m and 15m data end 2026-08-12, so the run read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-08-12, role: full_history}
forward_span_looks: 1
tables: [feature_vectors, forward_returns, market_data_ohlcv_tradeable]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-per-symbol-trend-regime.md
  - .planning/todos/completed/303-per-symbol-trend-regime-null-arm-tested-candidate.md
  - scripts/analysis/per_symbol_trend_candidates_stage1_pilot.py
  - scripts/analysis/per_symbol_regime_candidates_stage2_orthogonality.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-todo304-percentile-rank-regimes]
---

# Todo 303 per-symbol trend regime candidates (hurst_rank, autocorr_rank)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row Todo 303; `docs/research/measurement-per-symbol-trend-regime.md`

## What was tried

The per-symbol HMM's K=5 labels, named trend, were found by a null arm in phases 171 and 172 to
separate on volatility, not trend. That undercut the premise that killed Hurst and
autocorrelation-sign at Gate 0, so todo 303 re-tested both as causal per-symbol percentile
ranks. Stage 1 validated the mechanism (10 of 10 causality checks pass, non-degenerate
distributions). Stage 2 checked orthogonality to `regime_volatility`. Stage 3 ran a
day-clustered walk-forward Sharpe-uplift test of `momentum_z_fast` and `momentum_z_mid` under
`regime_volatility`-stratified terciles, against a 200-replicate null-arm control, with BH-FDR
over 20 tests.

## What was found

Both candidates cleared Stage 2 and failed Stage 3 at both timeframes. The only cell to clear
the raw null-arm bar was `hurst_rank` with `momentum_z_fast` at 5m (null_p 0.030), and it does
not survive BH-FDR (bh_p 0.475). No candidate sharpens IC beyond `regime_volatility`; the Gate 0
rejection is reaffirmed on fresh evidence.

## Known defects

See front matter. The failing criterion is the standing null-arm (scrambled-data) control the
project requires of every regime candidate.

## Why closed

The ledger froze it DEAD, closed. It cannot be rerun as-is: the recipe scripts are deleted by
186-16, `feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

Every number is copied from the Stage 2 and Stage 3 result sections of
`docs/research/measurement-per-symbol-trend-regime.md`. No query was run and no script was
rerun.

The plan named `per_symbol_trend_candidates_stage1_pilot.py` as the expected script. The doc
names `per_symbol_regime_candidates_stage3_falsification.py` (shared with todo 304, one run
covering all five candidates) as the script that produced the verdict numbers, so that is
`recipe.script`; the Stage 1 pilot and Stage 2 script are in `sources`. `recipe_commit` is
`git log -1 --format=%H --before="2026-09-01 23:59:59" -- scripts/analysis/per_symbol_regime_candidates_stage3_falsification.py`.
`tables` are the relations in that script's SQL.

The span start follows the 186-01 corpus start convention; the doc gives only cell counts. The
end (2026-08-12) is the last date ingestion delivered bars per the statistical factor residual
doc. `forward_span_looks` is 1: the shared Stage 3 run read data at or after 2025-12-24. It is
counted here and not on the todo 304 card, which shares the run.
