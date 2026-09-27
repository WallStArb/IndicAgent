---
card_id: legacy-em-cal-emission-threshold
kind: legacy_verdict
title: EM-CAL emission threshold sweep and the tradable-alpha question
idea: Sweep the alpha emission threshold per timeframe and regime to find a net-of-cost, per-event tradable edge in the champion ensemble's emitted events.
verdict: INCONCLUSIVE
verdict_date: 2026-07-19
recipe:
  spec: null
  script: scripts/ops/alpha/ops_emission_threshold_sweep.py
  recipe_commit: e2680aa2cb89a126f4b9820345ccba2a6ac9589f
results:
  - name: q5_verdict
    value: "no real, tradable, cost-surviving alpha at the swept horizon: gross edge 0.0-1.1 bp per event against a never-calibrated >= 1-2 bp realistic cost floor"
    source: docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md#q5
  - name: best_cell_fragility
    value: "5m/high_neutral at threshold 1.8 flips sign by year and 2021 alone (1019 of 3232 events) contributes roughly 85% of the cell's total net edge"
    source: docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md#q2
  - name: corrupt_print_finding
    value: "the sweep's largest standout (5m/low_bull stratum mean 0.01052) was one corrupt 2007 UUP print (bar 2007-06-20 19:00, open 1000, return_fast 3.686); ex-UUP/XRT the stratum mean is ~0.5 bp; 27 forward_returns rows across 13 (symbol, tf) pairs have abs(return_fast) > 0.5"
    source: docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md#q4
  - name: cost_calibration_state
    value: "alpha.quant.cost_hurdle.{5m,15m,1h,1d} all 0.0; no cost calibration ever run in the repo"
    source: docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md#q3
known_defects:
  - "The falsification check never ran under conditions capable of falsifying: the horizons where measured IC could plausibly clear costs (5/20-bar holds, IC 0.017-0.038) were never swept pending the lookahead grid fix (todo 146)."
  - Mean-based strata had no defense against corrupt prints; the rank-based IC layers were immune (Spearman throughout), which is why the IC findings survived and the mean-return numbers required forensics.
spans_looked_at:
  - {start: 2006-09-01, end: 2026-07-19, role: full_history}
forward_span_looks: 0
tables: [ensemble_alpha, forward_returns, alpha_events]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md
  - docs/research/measurement-alpha-emission.md
  - db:ensemble_weights
  - db:feature_ic_scores
related_cards: [legacy-ensemble-champion]
---

# EM-CAL emission threshold sweep and the tradable-alpha question

## What was tried

`ops_emission_threshold_sweep.py` swept the emission threshold per timeframe and regime over
`ensemble_alpha` joined to `forward_returns`, computing per-event directional net return
(direction_sign * forward_return - cost_hurdle) for emitted events, to answer whether the
champion ensemble emits a tradable, cost-surviving alpha.

## What found

At the only horizon swept (1-bar), the gross edge is 0.0 to 1.1 bp per event against a
realistic cost floor of at least 1-2 bp that was never calibrated (`cost_hurdle` all 0.0).
The best cell is dominated by one calendar year and the largest standout was a single corrupt
2007 price print that passed the volume>0 tradeable filter. The review's Q5 answer: no real,
tradable, cost-surviving alpha, while the rank-IC signal underneath is real and coherent
(positive in 27 of 28 measured ensemble-IC cells). What would flip the verdict is specified in
the doc: a per-regime sweep at the hold horizon where the IC lives, against a spread-
calibrated non-zero cost hurdle, with clustered standard errors and a corrupt-print guard,
confirmed once through the OOS gate.

## Known defects

Unswept horizons pending todo 146; no cost calibration anywhere; mean-return fragility to
corrupt prints (todo 148 price-sanity guard filed).

## Why closed

The sweep was never completed under falsifiable conditions, and the emission-threshold route
was retired with the old chain before the decisive horizons were measured. INCONCLUSIVE per
the review's own framing: a measurement-integrity call plus a sequencing recommendation, not a
redesign proposal.

## Where the numbers came from

All numbers are copied from `docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md`
(sections Q2-Q5), whose claims were independently verified against live code and DB on
2026-07-19, and from `docs/research/measurement-alpha-emission.md`. No query was re-run for
this card; the doc's own SQL is embedded in its appendix.
