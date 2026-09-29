---
card_id: legacy-tsmom-sleeve
kind: legacy_verdict
title: Classic time-series momentum on the 13-symbol cross-asset sleeve (phase 181)
idea: "Sign-and-volatility 12-month time-series momentum on the 13-symbol cross-asset sleeve carries trend-timing information beyond a time-shifted copy of the same signal."
verdict: FAIL
verdict_date: 2026-09-24
recipe:
  spec: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md
  script: scripts/analysis/sleeve_walk_forward/run.py
  recipe_commit: 0c33a2596e2906dab905f4d6ddc68f1e32827091
results:
  - name: observed_sharpe_gross
    value: "0.47 (2013-01-01 to 2025-12-23)"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: null_median_sharpe
    value: "0.27 (K = 3,389 shifts; 5th to 95th percentile -0.08 to 0.67)"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: excess_sharpe
    value: "+0.19 (0.194), stationary-bootstrap CI [-0.32, +0.73]"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: permutation_p
    value: "0.221 (ledger: 0.22)"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: subperiod_mean_daily_excess_bp
    value: "+0.54, +0.76, +0.45 (3 of 3 positive: 2013-2016, 2017-2020, 2021-2025)"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: diagnostics
    value: "Sortino 0.65, max drawdown 16.4% of log wealth, hit rate 53.5%"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
  - name: n_tested
    value: 18
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: power_gates
    value: "V2 false-positive rate 2.0%; V3 power 54% (CI 47-61%) at planted excess 0.50 and 74.5% (CI 68-81%) at 0.72"
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#9-gates-before-the-real-run
  - name: run_commit
    value: 0c33a2596e2906dab905f4d6ddc68f1e32827091
    source: docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md#10-result-2026-09-24
known_defects:
  - "Underpowered on 13 names: a FAIL is recorded as no detectable trend timing at this sample size, not no premium. Power was 54% at excess 0.50."
  - "TLT has no signal until 2017-02 because its history starts 2016-02-03 in this corpus (listed since 2002; ohlcv_empty_history, todo 424)."
  - "The sleeve is 13 symbols selected on correlation only (phase 174 Gate A), all listed today, so survivorship applies."
  - "Most of the book's return is drift a shifted copy also earns; the timing part is below detection at 13 years."
  - "The panel end is the last session before oos_start; the run did not read the forward span."
spans_looked_at:
  - {start: 2011-01-03, end: 2025-12-23, role: in_sample}
forward_span_looks: 0
tables: [market_data_ohlcv_tradeable, forward_returns, instruments, instrument_tags, feature_vectors, market_regimes, concept_registry]
status_now: reopened
reopened_as: "construction-verdict-ledger.md section 2: new construction, residual momentum (12-1 month on S1 residual returns, Blitz, Huij and Martens 2011)"
reproducible: false
sources:
  - docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md
  - scripts/analysis/sleeve_walk_forward/signals.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-phase179-sleeve-walk-forward]
---

# Classic time-series momentum on the 13-symbol cross-asset sleeve (phase 181)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `tsmom_sleeve`; `docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md`

## What was tried

Pre-registered (frozen 2026-09-24, commit 0c33a2596, before any real-data number existed for the
signal): `alpha = ln(close[d] / close[d-252])` on the 13-symbol cross-asset sleeve
(GLD, DBA, DBB, DBC, URA, TLT, UUP, VIXY, EMLC, HYG, XOM, DHI, PGR), fixed positive sign,
sign-over-volatility weights normalized to gross 1, signal at close, entry and exit at the next
two opens. It ran through the phase 179 evaluator with the memory-aware whole-panel shift null
(the whole signal panel circularly shifted, the portfolio rerun on every copy) over 2013-01-01 to
2025-12-23.

## What was found

Observed gross Sharpe 0.47 against a null median of 0.27, an excess of +0.19 with a
stationary-bootstrap CI of [-0.32, +0.73] and permutation p 0.221 (K=3,389). Sub-period excess
is positive in all three sub-periods. It fails on p, not on stability. Most of the book's return
is drift a shifted copy also earns; the timing component is below detection at 13 years.

## Known defects

See front matter. Power was 54% at excess 0.50 (V3), so the FAIL is a statement about this
sample size.

## Why closed

The ledger froze it FAIL, closing classic TSMOM and its variants (unsigned, 12-1, other
lookbacks) on this sleeve. It is reopened in ledger section 2 (owner decision 2026-09-25) as a
new construction, residual momentum on S1 residual returns, because the sleeve was underpowered
at 13 names. This card stays the closed-verdict record. It cannot be rerun as-is: the recipe
package `scripts/analysis/sleeve_walk_forward/` is deleted by 186-16, `feature_vectors` and the
snapshot inputs are rebuilt, and E15 changed the gates.

## Where the numbers came from

Every number is copied from section 10 of the pre-registration (result record) and the ledger
row; power gates are from the same document's V2 and V3 lines. No query was run and no script was
rerun. The record names the verdict file `logs/phase181/s4_12f955d9aca8f18f.json` (untracked,
gitignored) in prose only.

`recipe_commit` is the explicit run and freeze commit the spec names (0c33a2596), resolved with
`git rev-parse 0c33a2596`. `git cat-file -e 0c33a2596:scripts/analysis/sleeve_walk_forward/run.py`
succeeds, and section 10 states one run at 0c33a2596 on a clean tree, so the date rule was not
needed. `signals.py` (the TSMOM signal definition) is in `sources`. `tables` are the relations the
harness's S0 snapshot node reads (`from market_data_ohlcv_tradeable`, `feature_vectors`,
`market_regimes`, `instruments`, `concept_registry`; `join forward_returns`, `instrument_tags`);
the TSMOM signal itself consumes only closes from `market_data_ohlcv_tradeable`.

The span is the pre-registration's panel, from the first session of 2011 (the warmup start) to
the last session before `oos_start`. `forward_span_looks` is 0: the panel ends before
2025-12-24 and the section 8 holdout (S5, read only for an ACT-level result) is not touched by this run.
