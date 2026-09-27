---
card_id: legacy-phase148-score-01-03
kind: legacy_verdict
title: Phase 148 alpha scoring system (SCORE-01/02/03)
idea: Score the ensemble alpha per (symbol, tf, regime) cell into deciles with bootstrap CIs, then prove signal (Gate 1) and execution (Gate 2) out-of-sample before any promotion.
verdict: INCONCLUSIVE
verdict_date: 2026-07-23
recipe:
  spec: null
  script: services/alpha_scorer.py
  recipe_commit: ff8a477b1e4c39ac72428bfba160c14eecdc9aae
results:
  - name: alpha_strategy_scores_rows
    value: 120
    source: db:alpha_strategy_scores
  - name: spy_5m_high_bear_decile1
    value: "n=6522, clusters=859, win=0.4620, sharpe_annualized=3.1025, max_dd=4.005, ic_alpha_score_corr=0.5879, run 2026-07-22 20:36:19+00"
    source: db:alpha_strategy_scores
  - name: spy_5m_high_bear_decile8
    value: "n=6521, clusters=937, win=0.4844, sharpe_annualized=-1.6184, max_dd=NULL, run 2026-07-22 20:36:19+00"
    source: db:alpha_strategy_scores
known_defects:
  - Scores were computed for one (symbol, tf, regime) stratum family in a single 2026-07-22 batch and never refreshed; no recurring scoring cadence existed.
  - The scorer's signal gate passed but the execution gate failed (see legacy-phase148-oos-gates), so the score direction was killed on paper; that ledger verdict is recorded separately.
spans_looked_at:
  - {start: 2025-12-24, end: 2026-07-22, role: forward_span}
forward_span_looks: 2
tables: [alpha_strategy_scores, alpha_frames]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/plans/archive/2026-07-22-phase148-promotion-decision.md
  - .planning/milestones/v3.1-phases/148-alpha-scoring-system/148-03-SUMMARY.md
  - .planning/milestones/v3.1-phases/148-alpha-scoring-system/148-05-SUMMARY.md
  - db:alpha_strategy_scores
related_cards: []
---

# Phase 148 alpha scoring system (SCORE-01/02/03)

## What was tried

SCORE-01/02/03 built `alpha_scorer.py`: per (symbol, tf, regime) decile scoring of
`alpha_score`, with day-clustered bootstrap CIs, feeding the phase 148 OOS proof gates.

## What was found

The scorer ran once against the OOS side (batch stamped 2026-07-22 20:36:19+00), leaving 120
stored rows. In the stored SPY/5m/high_bear block, decile 1 shows sharpe_annualized 3.10 with
max_drawdown 4.0 while decile 8 shows -1.62, i.e. the stored scores rank monotonically within
that stratum. The signal gate passed (140 of 640 reliable cells qualify); the execution gate
failed (3 of 5 criteria), and the overall phase 148 decision was "Do not promote the v3.0
AlphaEngine to live trading capital at this time".

## Known defects

One-shot scoring, no cadence; coverage only for the strata present in the 2026-07-22 batch.
The chain's verdict history (phase 148 `alpha_score_directional`, killed on paper) is a ledger
row recorded by the construction-verdict ledger and loaded separately in phase 186 plan 02.

## Why closed

The scoring machinery itself worked, but its decisive execution gate failed and the process
was retired with the old chain, so the evidence is INCONCLUSIVE for the scorer in isolation:
signal proof passed, execution proof failed, no re-run was permitted.

## Where the numbers came from

Read 2026-09-27:

```sql
SELECT count(*) FROM alpha_strategy_scores;  -- 120
SELECT symbol, tf, regime, alpha_score_decile, sample_n, n_clusters, win_rate,
       sharpe_annualized, max_drawdown, ic_alpha_score_corr, ci_lower, ci_upper, run_ts
FROM alpha_strategy_scores ORDER BY run_ts DESC;  -- SPY/5m/high_bear block quoted above
```

Gate outcomes are quoted from `docs/plans/archive/2026-07-22-phase148-promotion-decision.md`.
