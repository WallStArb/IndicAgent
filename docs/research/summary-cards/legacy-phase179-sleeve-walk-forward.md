---
card_id: legacy-phase179-sleeve-walk-forward
kind: legacy_verdict
title: Phase 179 cross-asset sleeve walk-forward with production ensemble weights (three calibrated arms)
idea: "The production ensemble signal, refitted yearly on point-in-time data, carries allocation information across the 13-symbol cross-asset sleeve beyond a time-shifted copy of itself."
verdict: FAIL
verdict_date: 2026-09-25
recipe:
  spec: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md
  script: scripts/analysis/sleeve_walk_forward/run.py
  recipe_commit: 5fa10430a9a411189e04db57085edf5faf4be2b1
results:
  - name: arm_ic_proportional
    value: "observed Sharpe 0.198, null median -0.018, excess +0.216 (ledger +0.22), CI [-0.326, +0.677], adjusted p 0.360, sub-periods 2 of 3 positive (-2.5, +1.6, +5.2 bp per day)"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#125-rerun-record-2026-09-25-sleeve_verdict--fail-fidelity--ok
  - name: arm_vol_normalized
    value: "observed Sharpe -0.177, null median -0.031, excess -0.146 (ledger -0.15), CI [-0.750, +0.370], adjusted p 0.881, 1 of 3 sub-periods positive"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#125-rerun-record-2026-09-25-sleeve_verdict--fail-fidelity--ok
  - name: arm_mean_variance
    value: "observed Sharpe -0.126, null median -0.021, excess -0.106 (ledger -0.11), CI [-0.645, +0.386], adjusted p 0.855, 1 of 3 sub-periods positive"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#125-rerun-record-2026-09-25-sleeve_verdict--fail-fidelity--ok
  - name: null_design
    value: "2,885 admissible shifts, shift memory 758, Westfall-Young across 3 arms, N_tested 18"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#125-rerun-record-2026-09-25-sleeve_verdict--fail-fidelity--ok
  - name: power_v3_planted_fast_edge
    value: "69% (CI 63-75%) at realized excess 0.71; 83% (CI 78-88%) at realized excess 0.85"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#122-freeze-record
  - name: power_v3b_slow_return_built_edge
    value: "0% (0/200) at both planted sizes; calibrated arms' mean excess Sharpe -0.38 and -0.52"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#122-freeze-record
  - name: v2_false_positive_rate
    value: "6.0% (12/200; CI 2.7-9.3%), inside 5% +/- 3.1%"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#122-freeze-record
  - name: fidelity
    value: "OK (V1, V4, V5); V4 31,800 keys equal; V5 placebo detected in 362 of 362 containing-lookahead cells, noise 16 of 4,197"
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#125-rerun-record-2026-09-25-sleeve_verdict--fail-fidelity--ok
  - name: in_sample_diagnostic_contrast
    value: "the 2026-09-22 in-sample Sharpe about 1.19 portfolio diagnostic does not survive point-in-time weights"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: freeze_commit
    value: da0548a96a4d2594b813a94d7d2b64342fcda5f9
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md
  - name: frozen_run_code_commit
    value: a64af3d1a96b3f7ed16a0be95f507fcc30e592be
    source: docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md#122-freeze-record
known_defects:
  - "The frozen run (2026-09-25) ended FIDELITY BROKEN with no token: the section 6 rule (alpha NaN on days whose equity stratum has no weights) interacted with section 7's 95% calibration-coverage rule, so only 2 of 13 calibration segments admitted any symbol and the observed book held a position on 447 of 3,265 days; a shifted panel moved the NaN pattern so that no segment calibrated, giving a zero-variance series. No observed or null Sharpe was printed or read in between."
  - "The rerun under methodology-change-ledger E14 (owner decision, todo 425) changed the section 7 calibration rule (IC computed when at least coverage_fraction of the trailing window's finite-alpha days also have a finite forward return), was pinned before the rerun, and superseded the frozen run's 12.2 results. The numbers above are the E14 rerun's; the recipe_commit is the main commit the rerun executed at."
  - "V3b: the calibrated arms have 0% power on slow return-built edges of the planted sizes, so this FAIL says nothing about such edges."
  - "A reported-only S3 diagnostic is mislabelled: the null_median shape measures (hit rate 0.0, skew -55, kurtosis 3,086) are the shape of the day-by-day median series across shifts, not the median of each shift's own measures."
  - "Residual biases: survivorship and present-day routing in the pooling universe (todo 376, optimistic direction); design-time snooping; TLT history starting 2016-02-03; the holdout was viewed once in aggregate."
  - "The S0 snapshot directory (logs/phase179/official/, 1.4 GB, untracked) was deleted 2026-09-29; its hash (snapshot_97719acbf3dd7ee3) and the frozen rerun_e14 stage payloads in logs/phase179 remain the identity record, and the frozen S3 pickles are what the 186-03 determinism tool loads."
spans_looked_at:
  - {start: 2011-01-03, end: 2025-12-23, role: in_sample}
forward_span_looks: 0
tables: [feature_vectors, forward_returns, market_regimes, market_data_ohlcv_tradeable, instruments, instrument_tags, concept_registry, feature_ic_scores]
status_now: reopened
reopened_as: "construction-verdict-ledger.md section 2: corpus features through the ensemble, admitted as feature families on prior with walk-forward ridge weights and no per-feature IC gate"
reproducible: false
sources:
  - docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md
  - docs/plans/methodology-change-ledger.md
  - scripts/analysis/sleeve_walk_forward/refit.py
  - scripts/analysis/sleeve_walk_forward/evaluate.py
  - scripts/analysis/sleeve_walk_forward/v5.py
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-ensemble-champion, legacy-tsmom-sleeve]
---

# Phase 179 cross-asset sleeve walk-forward with production ensemble weights (three calibrated arms)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row Phase 179 sleeve walk-forward; `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`; `docs/plans/methodology-change-ledger.md` E14

## What was tried

Pre-registered (frozen 2026-09-25, commit da0548a96, code a64af3d1a): production ensemble weights
(equity-group pooled 1d IC, yearly refits 2011 to 2025, point-in-time) turned into a portfolio on
the 13-symbol sleeve through three calibrated arms, `ic_proportional`, `vol_normalized` and
`mean_variance`, evaluated 2013 to 2025 against a whole-panel shift null (the signal panel
circularly shifted and the full pipeline, calibration included, rerun on every copy) with
Westfall-Young adjustment across the three arms. Fidelity gates V1 to V6 check the harness
against production before any verdict is read.

## What was found

No arm qualifies; the best adjusted p is 0.36. Excess Sharpe is +0.22 for `ic_proportional`
(CI -0.33 to +0.68, adjusted p 0.36, sub-periods negative, positive, positive), -0.15 for
`vol_normalized` (adjusted p 0.88) and -0.11 for `mean_variance` (adjusted p 0.85), over 2,885
admissible shifts with memory 758. The in-sample Sharpe of about 1.19 from the 2026-09-22
portfolio diagnostic does not survive point-in-time weights. V3 power on the planted fast edge
was 83% at excess 0.85.

## Known defects

See front matter. The first run ended FIDELITY BROKEN on a calibration-coverage defect with no
performance number read; the E14 rerun's numbers are the record. V3b showed the arms have 0%
power on slow return-built edges, so this FAIL says nothing about those.

## Why closed

The ledger froze it FAIL on the 13-ETF sleeve. It is reopened in ledger section 2 (owner
decision 2026-09-25) because the vehicle was wrong: 13 names, arms with 0% power on slow edges,
and production's BH-FDR selection on thin regime-by-timeframe cells (the phase 148 failure).
The corpus of about 290 columns has never been tested as a book on the 233-name residual panel.
It enters as feature families with walk-forward ridge weights and no per-feature IC gate, and
this card stays the closed-verdict record. It cannot be rerun as-is: the harness package
`scripts/analysis/sleeve_walk_forward/` is deleted by 186-16, `feature_vectors` is rebuilt and
the old ensemble tables it mirrored are dropped under phase 186, and E15 changed the gates.

## Where the numbers came from

Arm numbers and the null design are copied from section 12.5 (rerun record) of the
pre-registration; V2, V3, V3b and fidelity numbers from section 12.2 (freeze record); the
in-sample contrast from the ledger row. No query was run and no script was rerun. Untracked
artifacts under `logs/phase179/rerun_e14/` are named here in prose only.

`recipe_commit` follows the spec's explicit run commit: section 12.5 says the E14 rerun executed
at main `5fa10430a`, resolved with `git rev-parse 5fa10430a`, and `git cat-file -e
5fa10430a9a411189e04db57085edf5faf4be2b1:scripts/analysis/sleeve_walk_forward/run.py` succeeds.
That differs from the freeze commit the plan lists (da0548a96), because the recorded numbers come
from the rerun; the freeze and frozen-run code commits are in `results` as `freeze_commit` and
`frozen_run_code_commit`. `refit.py`, `evaluate.py` and `v5.py` are in `sources`.

`tables`: the harness's S0 snapshot node reads `feature_vectors`, `market_regimes`,
`market_data_ohlcv_tradeable`, `instruments`, `concept_registry`, `config_state` (APR, left out),
and joins `forward_returns` and `instrument_tags`; it never reads `ensemble_weights`. The refit
re-derives weights in process through `ensemble_trainer`'s selection and `stratum_fit`, and V4
compares the result against production's `feature_ic_scores`, so that table is listed.

The span is the pre-registration's panel, from the first session of 2011 (warmup start; trading
window 2013 onward) to the last session before `oos_start`. `forward_span_looks` is 0: the run
ended before 2025-12-24 (`end_exclusive` 2025-12-24T05:15Z) and the holdout was not read.
