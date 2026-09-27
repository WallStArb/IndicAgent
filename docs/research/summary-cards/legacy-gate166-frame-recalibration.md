---
card_id: legacy-gate166-frame-recalibration
kind: legacy_verdict
title: Phase 166 frame execution recalibration (gate166_baseline, gate166_scalar)
idea: Recalibrate the frame execution rules (baseline and scalar candidates) so the frame simulation captures the Gate 1 signal as profitable OOS PnL.
verdict: FAIL
verdict_date: 2026-07-23
recipe:
  spec: null
  script: scripts/analysis/gate166_frame_recalibration_eval.py
  recipe_commit: 8c86cc4810466b75c104677997351550ed459ffd
results:
  - name: gate166_baseline
    value: "fail, 33892 frames, 69 OOS days: c2 ci_lower=-0.1215, c3 sharpe=0.3851 (threshold 0.5), c4 max_dd ratio=9.596 (threshold 0.25); 7 eligible regime/tf cells"
    source: gate_look_log:gate166_baseline
  - name: gate166_scalar
    value: "fail, 28100 frames, 65 OOS days: c2 ci_lower=-0.0450, c3 sharpe=0.4408, c4 max_dd ratio=26.178; 7 eligible regime/tf cells"
    source: gate_look_log:gate166_scalar
known_defects:
  - Both candidates failed on the same pooled criteria as gate2_execution; only 2 of 8 regime cells were evaluable (mid_bull long/short), so regime-conditional performance stayed uncharacterized.
  - Frames covered 5m/15m only (disclosure.tfs ['15m','5m'] in both evidence rows).
spans_looked_at:
  - {start: 2025-12-24, end: 2026-07-23, role: forward_span}
forward_span_looks: 2
tables: [alpha_frames]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - gate_look_log:gate166_baseline
  - gate_look_log:gate166_scalar
  - .planning/milestones/v3.1-phases/166-frame-execution-recalibration/166-VERIFICATION.md
  - db:gate_evaluations
related_cards: [legacy-phase148-oos-gates]
---

# Phase 166 frame execution recalibration (gate166_baseline, gate166_scalar)

## What was tried

After Gate 2 failed, phase 166 recalibrated the frame execution rules and re-evaluated the
frozen SHADOW-REVIEW criteria on two candidates: `baseline` (the unchanged recalibration
starting point) and `scalar`, using `gate166_frame_recalibration_eval.py` against
`alpha_frames` and the champion weight epoch.

## What was found

Both looks failed on 2026-07-23 (13:07:38 and 13:21:13). Baseline: sharpe 0.385, c2 CI lower
-0.121, c4 drawdown ratio 9.60 over 33,892 frames. Scalar improved Sharpe to 0.441 and c2 to
-0.045 but blew out c4 to 26.18. Neither candidate captured the Gate 1 signal as profitable
OOS PnL, and the evaluable regime coverage stayed at 2 of 8 cells.

## Known defects

Same narrow regime coverage as Gate 2; 5m/15m only; the c5 criterion remained a documented
c7 proxy (no recurring ensemble_ic_engine cadence to form the trailing split).

## Why closed

Both recalibration candidates failed their gate looks; frame recalibration was abandoned and
the frame layer retired with the old chain. Verdict FAIL.

## Where the numbers came from

All numbers are quoted verbatim from the `gate_evaluations.evidence` rows for
`gate_id='gate166_baseline'` and `gate_id='gate166_scalar'` (read 2026-09-27), whose lines are
mirrored in `.planning/gate_look_log.jsonl`.
