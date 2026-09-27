---
card_id: legacy-phase142b-frames-frame04
kind: legacy_verdict
title: Phase 142B frame simulation and counterfactual FRAME-04
idea: Simulate stop/target/hold trade frames against every alpha event and track the counterfactual PnL_R, with FRAME-04 as the phase-exit day-clustered bootstrap gate.
verdict: DEAD
verdict_date: 2026-09-26
recipe:
  spec: null
  script: services/counterfactual_tracker.py
  recipe_commit: adf5afa77d3bccd2a82ae8eb85b18f24ed52a7f5
results:
  - name: alpha_frames_rows
    value: 0
    source: db:alpha_frames
  - name: frame_gate_implementation
    value: day-clustered block bootstrap, gross pnl only, min_strategy_n respected, IC-row-age instrumented; verified but never evaluated on real frames
    source: .planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-VERIFICATION.md
known_defects:
  - alpha_frames never received rows from a live cadence; the 142B verification confirms 0 rows is the expected state and the FRAME-04 gate was deferred to an ops run that never happened.
  - The single gate2_execution row (2026-07-23) was later accepted as satisfying both SCORE-03 and Phase 142B's frame-quality gate per D-08, so FRAME-04 never ran as its own gate look.
spans_looked_at: []
forward_span_looks: 0
tables: [alpha_frames]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - .planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-VERIFICATION.md
  - .planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-02-SUMMARY.md
  - services/alpha_frame_writer.py
  - db:alpha_frames
related_cards: [legacy-phase148-oos-gates]
---

# Phase 142B frame simulation and counterfactual FRAME-04

## What was tried

Phase 142B built the frame simulation layer: `alpha_frame_writer.py` writes simulated
stop/target/hold frames per alpha event, `counterfactual_tracker.py` carries counterfactual
PnL_R and evaluates the FRAME-04 phase-exit gate (day-clustered block bootstrap on gross frame
PnL, min_strategy_n respected).

## What was found

The implementation was verified complete (10/10 APR keys live, FRAME-01..04 satisfied in
code), but `alpha_frames` holds 0 rows from any live cadence. The frame population used by
phase 148's Gate 2 (33,892 closed frames) came from a one-off batch, and its evaluation was
recorded as `gate2_execution`, not as a FRAME-04 look. FRAME-04 never produced its own gate
verdict.

## Known defects

No recurring cadence ever populated `alpha_frames`; the empty-table state was permanent. The
gate's single real evaluation was folded into phase 148's Gate 2 row per D-08.

## Why closed

The process was abandoned without its own gate look: phase 148's Gate 2 (FAIL) is the only
execution-proof evidence this machinery ever produced, and the unified design retires the old
chain. DEAD, not FAIL: FRAME-04 itself never ran.

## Where the numbers came from

Row count read 2026-09-27:

```sql
SELECT count(*) FROM alpha_frames;  -- 0
```

All other statements are quoted from `.planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-VERIFICATION.md`.
