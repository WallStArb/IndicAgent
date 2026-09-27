---
card_id: legacy-phase148-oos-gates
kind: legacy_verdict
title: Phase 148 OOS proof gates (gate1_signal pass, gate2_execution fail)
idea: "Two independent irreversible OOS gates on the champion ensemble: does alpha_score predict forward returns out-of-sample, and does the frame simulation capture that signal as profitable PnL."
verdict: FAIL
verdict_date: 2026-07-23
recipe:
  spec: null
  script: scripts/ops/corpus/ops_oos_gate1_signal_eval.py
  recipe_commit: ff8a477b1e4c39ac72428bfba160c14eecdc9aae
results:
  - name: gate1_signal_result
    value: pass, 640 reliable cells, 140 qualify (21.875%) against a 2% floor, 5m/15m only
    source: gate_look_log:gate1_signal
  - name: gate1_signal_breakdown
    value: "qualifying cells by tf/scale: 5m fast 6, mid 11, slow 14, extended 34; 15m fast 0, mid 27, slow 21, extended 27 (of 80 each)"
    source: docs/plans/archive/2026-07-22-phase148-promotion-decision.md
  - name: gate2_execution_result
    value: fail, 33892 frames over 69 OOS days; c1 pass, c2 ci_lower=-0.1215 fail, c3 sharpe=0.3851 fail (threshold 0.5), c4 max_dd ratio=9.596 fail (threshold 0.25), c5 proxy pass; 3 of 5 fail
    source: gate_look_log:2026-07-23T00:26:31.223260Z
known_defects:
  - "gate1_signal measured 5m/15m only: ensemble_alpha had zero OOS rows at tf=1h and tf=1d, so the PASS is not a full 4-timeframe signal proof (todo 173)."
  - forward_returns had to be backfilled past the OOS boundary before Gate 1 could run at all (human sign-off recorded in the promotion decision doc).
  - "The 2026-07-23T00:26:31Z look (gate2_execution) has no gate_id key in gate_look_log.jsonl; its identity is established by the gate_evaluations row."
  - c4 was computed via a path-dependent cumsum with ~22-way bar_ts ties; the frozen baseline was never bit-reproducible until a symbol tie-break was added (~0.001 absolute divergence found and resolved before the real run).
spans_looked_at:
  - {start: 2025-12-24, end: 2026-07-23, role: forward_span}
forward_span_looks: 2
tables: [ensemble_alpha, forward_returns, alpha_frames]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/plans/archive/2026-07-22-phase148-promotion-decision.md
  - docs/plans/OOS-EVAL-PROTOCOL.md
  - gate_look_log:gate1_signal
  - gate_look_log:2026-07-23T00:26:31.223260Z
  - db:gate_evaluations
related_cards: []
---

# Phase 148 OOS proof gates (gate1_signal pass, gate2_execution fail)

## What was tried

Two independent, non-repeatable OOS gates per `docs/plans/OOS-EVAL-PROTOCOL.md`:
`ops_oos_gate1_signal_eval.py` (rank-IC of alpha_score against four forward-return horizons,
Fisher-z CI + BH-FDR, per cell) and `score03_gate2_execution_eval.py` (the frozen
SHADOW-REVIEW criteria on the 143.1-08-champion frame population).

## What was found

Gate 1 (2026-07-22T21:02:22Z, gate1_signal): PASS. 640 cells, all reliable, 140 qualifying
against a 2% floor, concentrated at longer lookaheads.

Gate 2 (2026-07-23T00:26:31Z, gate2_execution in gate_evaluations; the log line carries no
gate_id): FAIL. 33,892 closed frames, 69 OOS days; criteria c2/c3/c4 fail decisively
(ci_lower -0.1215, Sharpe 0.3851 vs 0.5, max drawdown ratio 9.596 vs 0.25); the regime-
stratified companion shows only 2 of 8 cells evaluated (both mid_bull). Overall decision:
do not promote.

## Known defects

5m/15m coverage only on Gate 1; forward_returns backfill across the OOS boundary was required
first; the c4 tie-order reproducibility issue documented above; the regime-stratified OOS
window was too narrow to characterize regime-conditional performance.

## Why closed

The execution gate failed, per protocol the gates cannot be re-run, and the phase 148 verdict
record (alpha_score_directional, killed on paper) belongs to the construction-verdict ledger;
this card records the gate looks themselves. Verdict FAIL per Gate 2.

## Where the numbers came from

Gate evidence is stored in `gate_evaluations`; the gate1_signal cell aggregate was computed
2026-09-27 with:

```sql
SELECT count(cell), count(*) FILTER (WHERE (cell->>'passes_fdr')='true'),
       count(*) FILTER (WHERE (cell->>'walk_forward_stable')='true')
FROM gate_evaluations g, jsonb_array_elements(g.evidence->'cells') cell
WHERE gate_id='gate1_signal';  -- 640 | 238 | 241
```

Gate 2 numbers are quoted verbatim from `gate_evaluations.evidence` for
`gate_id='gate2_execution'` (same date) and from the promotion decision doc.
