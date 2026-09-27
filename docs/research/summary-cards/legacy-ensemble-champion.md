---
card_id: legacy-ensemble-champion
kind: legacy_verdict
title: Production ensemble champion run_2025122405150000
idea: Train IC-weighted per-(symbol, tf, regime) ensemble weights over rank-normalized feature columns and score every bar, holding the weights frozen as the production champion through the v3.x chain.
verdict: FAIL
verdict_date: 2026-07-23
recipe:
  spec: null
  script: services/ensemble_trainer.py
  recipe_commit: ca4fd80e3a1087c9fbbac48f7057e31d123ced30
results:
  - name: ensemble_weights_rows
    value: 358
    source: db:ensemble_weights
  - name: ensemble_weights_cells
    value: "33 distinct (symbol, tf, regime) cells; 101 distinct feature names; tfs 5m/15m/1h/1d; regimes high_bear..mid_neutral (all nine)"
    source: db:ensemble_weights
  - name: ensemble_alpha_rows
    value: 106690090
    source: db:ensemble_alpha
  - name: alpha_events_rows
    value: 65622721
    source: db:alpha_events
  - name: manifest_run_2025122405150000
    value: "rows_total 358, rows_by_tf {5m: 103, 1h: 89, 15m: 84, 1d: 82}, status success, written 2026-09-24T21:51:43Z"
    source: .planning/corpus_manifests/ensemble_trainer__run_2025122405150000.json
  - name: manifest_run_2025122405150000_mv
    value: "rows_total 251, rows_by_tf {5m: 143, 15m: 92, 1d: 16}, status success, written 2026-07-09T13:52:41Z"
    source: .planning/corpus_manifests/ensemble_trainer__run_2025122405150000_mv.json
  - name: manifest_143_1_08_champion
    value: "rows_total 47, rows_by_tf {5m: 27, 15m: 20}, status success, written 2026-07-20T07:53:27Z; this was the weight epoch used by the phase 148 gates"
    source: .planning/corpus_manifests/ensemble_trainer__143.1-08-champion.json
known_defects:
  - "The champion never passed an execution gate: gate2_execution (weight epoch 143.1-08-champion) failed 3 of 5 criteria and the phase 148 decision was \"do not promote\"."
  - "The gate1_signal coverage limitation applies to the champion's own scoring coverage: zero OOS ensemble_alpha rows at tf=1h/1d (todo 173)."
spans_looked_at:
  - {start: 2006-09-01, end: 2025-12-24, role: in_sample}
forward_span_looks: 2
tables: [ensemble_weights, ensemble_alpha, alpha_events]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - .planning/corpus_manifests/ensemble_trainer__run_2025122405150000.json
  - .planning/corpus_manifests/ensemble_trainer__run_2025122405150000_mv.json
  - .planning/corpus_manifests/ensemble_trainer__143.1-08-champion.json
  - docs/plans/archive/2026-07-22-phase148-promotion-decision.md
  - docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md
  - db:ensemble_weights
  - db:ensemble_alpha
  - db:alpha_events
related_cards: [legacy-phase148-oos-gates, legacy-phase142a-ensemble-ic, legacy-em-cal-emission-threshold]
---

# Production ensemble champion run_2025122405150000

## What was tried

The nightly Ensemble Builder (`ensemble_trainer.py`) trained IC-weighted linear ensembles per
(symbol, tf, regime) cell over rank-normalized feature columns (Ledoit-Wolf IC Sharpe
weighting), froze the weights in `ensemble_weights` under version `run_2025122405150000`, and
scored every bar into `ensemble_alpha`, from which `alpha_publisher.py` emitted `alpha_events`
above per-timeframe thresholds. This was the v3.x production champion.

## What was found

The stored champion holds 358 weight rows over 33 distinct cells and 101 distinct features
across 5m/15m/1h/1d and all nine regimes. Its scoring output accumulated 106.7M
`ensemble_alpha` rows and 65.6M emitted `alpha_events`. Its proof gates failed: the phase 148
signal gate passed 5m/15m but the execution gate failed decisively on the 143.1-08-champion
epoch and the promotion decision was "do not promote the v3.0 AlphaEngine to live trading
capital at this time". The champion is retired whole by phase 186's drops.

## Known defects

Never promoted; 1h/1d OOS scoring coverage absent; the weight epoch naming carried aliases
(`run_2025122405150000` was noted in the promotion decision as possibly an alias of
`143.1-08-champion` with identical 5m/15m row counts, while the corpus manifests record them
as separate runs of 358 and 47 rows).

## Why closed

The champion failed its one irreversible execution gate and the unified research-to-production
design replaces the mechanism with the frozen-book pipeline. Verdict FAIL per the phase 148
promotion decision.

## Where the numbers came from

Row counts and cells read 2026-09-27:

```sql
SELECT count(*) FROM ensemble_weights;  -- 358
SELECT count(*) FROM (SELECT DISTINCT symbol, tf, regime, weight_version FROM ensemble_weights) t;  -- 33
SELECT count(DISTINCT feature_name) FROM ensemble_weights;  -- 101
SELECT count(*) FROM ensemble_alpha;  -- 106690090
SELECT count(*) FROM alpha_events;  -- 65622721
```

Manifest fields are quoted from the three committed `.planning/corpus_manifests/ensemble_trainer__*.json` files named in `sources`. Gate outcomes are quoted from the phase 148 promotion decision doc.
