---
card_id: legacy-jump-diffusion-decomposition
kind: legacy_verdict
title: Jump/diffusion decomposition (bipower-variation jump_ratio), SPY 15m pilot
idea: "A bipower-variation jump_ratio, computed from 1m sub-bar returns, adds incremental IC beyond garch_ratio and hurst."
verdict: DEAD
verdict_date: 2026-08-07
recipe:
  spec: docs/research/measurement-jump-diffusion-decomposition.md
  script: scripts/analysis/jump_diffusion_decomposition_spy_pilot.py
  recipe_commit: 803294354add0500e08238e7195fa1f04ec0c276
results:
  - name: pooled_partial_ic
    value: "0.0210, 95% CI [-0.0228, 0.0676], n=2206"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: regime_ranging_partial_ic
    value: "0.0253, CI [-0.1084, 0.1472], n=319"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: regime_transition_down_partial_ic
    value: "0.0253, CI [-0.0466, 0.1008], n=660"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: regime_transition_up_partial_ic
    value: "0.0269, CI [-0.0799, 0.1259], n=469"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: regime_trending_down_partial_ic
    value: "0.0679, CI [-0.0207, 0.1851], n=144"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: regime_trending_up_partial_ic
    value: "0.0116, CI [-0.0848, 0.1116], n=614"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
  - name: bootstrap_settings
    value: "n_boot=500, block_size=26, seed 42, min_reliable_n=100"
    source: docs/research/measurement-jump-diffusion-decomposition.md#result-spy-pilot-run-2026-08-07
known_defects:
  - "The pilot covers one symbol (SPY) at one timeframe (15m). Promotion to a wider symbol set was gated on more 1m history existing, and none was tested."
  - "market_data_ohlcv_tradeable 1m bars start 2026-03-23, so the sample is about four months (2,209 of 2,288 possible 15m bars joined), not the 20-year depth the design first assumed."
  - "The pilot's 1m window lies entirely at or after alpha.validation.oos_start (2025-12-24), so this run read forward-span data before any E15 accounting existed."
spans_looked_at:
  - {start: 2026-03-23, end: 2026-07-28, role: forward_span}
forward_span_looks: 1
tables: [feature_vectors, forward_returns, market_data_ohlcv_tradeable]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-jump-diffusion-decomposition.md
  - docs/research/data-edge-source-thesis.md
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Jump/diffusion decomposition (bipower-variation jump_ratio), SPY 15m pilot

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `jump_diffusion_decomposition`; `docs/research/measurement-jump-diffusion-decomposition.md`

## What was tried

Split each 15m bar's variance into a diffusion part and a jump part with Barndorff-Nielsen and
Shephard bipower variation over its constituent 1m returns, `jump_ratio = max(0, RV - BV) / RV`.
The test was pre-registered: does `jump_ratio` add partial Spearman IC on
`forward_returns.executable_open_to_open` beyond `garch_ratio` and `hurst`, pooled and within each
of the five per-symbol HMM regimes, with a day-clustered circular block bootstrap CI. If the CI
crosses zero pooled and in every regime, the idea is dead. Sub-bar returns came from
`market_data_ohlcv_tradeable` only, and the overnight gap was excluded.

## What was found

The CI crosses zero in the pooled cell (partial IC 0.0210, n=2,206) and in all five regimes, so
the pre-registered rule returns DEAD. The point estimates are small and positive everywhere; none
is distinguishable from zero. The thinnest regime cell (`trending_down`, n=144) cleared the
`min_reliable_n=100` floor but has the widest interval.

## Known defects

One symbol, one timeframe, four months of 1m history. The result is a pilot verdict on SPY 15m,
not a test of the idea across the universe.

## Why closed

The ledger froze it DEAD on the pre-registered rule and the idea was not promoted to a wider
symbol set. It cannot be rerun as-is: the recipe script is deleted by 186-16, `feature_vectors`
is rebuilt under phase 186, and E15 changed the gates a new test would face.

## Where the numbers came from

Every number is copied from the result table in
`docs/research/measurement-jump-diffusion-decomposition.md` (section "Result (SPY pilot, run
2026-08-07)"). No query was run and no script was rerun for this card.

`recipe_commit` is the last commit touching the script at or before the run date, from
`git log -1 --format=%H --before="2026-08-07 23:59:59" -- scripts/analysis/jump_diffusion_decomposition_spy_pilot.py`.
`tables` are the relations in the script's `FROM` and `JOIN` clauses plus the ones the doc names.
The span end (2026-07-28) is the data freshness the doc states for that run; the start is the
first 1m bar the doc gives. `forward_span_looks` is 1 because the single run read only data at
or after 2025-12-24; no other card counts it.
