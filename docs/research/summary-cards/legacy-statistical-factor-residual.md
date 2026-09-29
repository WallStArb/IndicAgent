---
card_id: legacy-statistical-factor-residual
kind: legacy_verdict
title: Statistical factor residual (PCA K-selection, causal fit, IC falsification)
idea: "Removing the top-K statistical (PCA) factors from returns leaves an idiosyncratic residual whose momentum signal has higher IC than the raw one."
verdict: DEAD
verdict_date: 2026-09-01
recipe:
  spec: docs/research/measurement-statistical-factor-residual.md
  script: scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py
  recipe_commit: a026dc1f2d579605092beebb496c616bb104235f
results:
  - name: stage1_k_full_universe
    value: "K=10 (Marchenko-Pastur and Parallel Analysis agree), N=231, T=349 days, 2026-08-11"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-1-k-selection-run-2026-08-11
  - name: stage1_k_pre_expansion_universe
    value: "K=5, N=80, T=349 days"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-1-k-selection-run-2026-08-11
  - name: stage3_universe
    value: "148 symbols, T=1984 days, K=11 re-measured, 83 refit segments, causality max diff 0.0, 55.9% mean variance removed"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: pooled_raw_ic
    value: "-0.0170, CI [-0.0223, -0.0121], n=231472"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: pooled_residual_ic
    value: "-0.0007, CI [-0.0060, 0.0047], n=231472"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: cross_sectional_raw_ic
    value: "-0.0018, CI [-0.0067, 0.0032]"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: cross_sectional_residual_ic
    value: "-0.0006, CI [-0.0051, 0.0037]"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: per_symbol_raw
    value: "median IC -0.0294, 8 of 148 pass BH-FDR"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
  - name: per_symbol_residual
    value: "median IC -0.0039, 8 of 148 pass BH-FDR"
    source: docs/research/measurement-statistical-factor-residual.md#result-stage-3-ic-falsification-run-2026-09-01
known_defects:
  - "Stage 1 K rests on T=349 days, the common window of the shortest-history symbol; the doc flagged a robustness check on a longer window and did not run it."
  - "The 148-symbol universe excludes recent IPOs and newer ETFs without about 8 years of history; 16 corpus-wide gap dates (12 from a live-ingestion outage, todo 366) were excluded by date, not interpolated."
  - "The falsification tested one signal, ctf_momentum (Wilder RSI) at tf=1d, return_mid (lookahead 5). Other features were not residualized."
  - "The trailing 2000-day window ends 2026-08-12, so the run read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2018-08-22, end: 2026-08-12, role: full_history}
forward_span_looks: 1
tables: [market_data_ohlcv_tradeable, forward_returns, feature_ic_scores]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-statistical-factor-residual.md
  - scripts/analysis/statistical_factor_residual_k_selection_pilot.py
  - scripts/analysis/statistical_factor_residual_stage2_causal_fit.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Statistical factor residual (PCA K-selection, causal fit, IC falsification)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `statistical_factor_residual`; `docs/research/measurement-statistical-factor-residual.md`

## What was tried

Three stages. Stage 1 selected the factor count K with Marchenko-Pastur and Parallel Analysis on
the instrument return matrix. Stage 2 fitted the PCA factors walk-forward (warmup 252 bars,
refit every 21) and checked causality by truncated-versus-full comparison. Stage 3 compared raw
against residualized `ctf_momentum` IC on three axes, pooled, cross-sectional and per-symbol
with BH-FDR, at tf=1d, `return_mid` (lookahead 5), using APR `n_boot=2000`, `block_size=10`.

## What was found

Residualizing did not raise IC on any axis; it pulled the signal toward zero (pooled IC from
-0.0170 to -0.0007, per-symbol median from -0.0294 to -0.0039), the opposite of the thesis. The
per-symbol BH-FDR passes are 8 of 148 for both raw and residual, about the count expected under
the null. Stage 1 gave K=10 for the 231-symbol universe (K=5 for the 80-symbol pre-expansion
set); Stage 3's 148-symbol universe re-measured K=11.

## Known defects

See front matter. The doc notes 5 of 5 discovery-track candidates now closed DEAD.

## Why closed

The ledger froze it DEAD on the pre-registered verdict rule. It cannot be rerun as-is: the
recipe scripts are deleted by 186-16, `feature_vectors` and `feature_ic_scores` are rebuilt or
retired under phase 186, and E15 changed the gates.

## Where the numbers came from

Every number is copied from the Stage 1 to Stage 3 result sections of
`docs/research/measurement-statistical-factor-residual.md`. The ledger row cites a memory file
for this verdict; memory files are outside the repo and not valid refs, so the doc is cited
instead. No query was run for the numbers and no script was rerun.

`recipe_commit` is `git log -1 --format=%H --before="2026-09-01 23:59:59" -- scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py`.
The Stage 1 and Stage 2 scripts are in `sources`. `tables` come from the Stage 3 script's
docstring ("reads market_data_ohlcv_tradeable, forward_returns, config_state (via
ConfigService), and feature_ic_scores (context only)"); `config_state` is APR and is left out.

The span end is 2026-08-12, the last date ingestion delivered bars per the doc. The start
(2018-08-22) is the 2000th trading day back from that end for SPY in `market_data_ohlcv_tradeable`,
found with a read-only `SELECT timestamp::date FROM market_data_ohlcv_tradeable WHERE symbol='SPY'
AND timeframe='1d' AND timestamp<='2026-08-12' ORDER BY timestamp DESC OFFSET 1999 LIMIT 1;`
run 2026-09-29. It approximates the doc's 2000-day trailing window. `forward_span_looks` is 1: the
Stage 3 run read data at or after 2025-12-24 and no other card counts it.
