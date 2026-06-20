---
phase: 127-clean-replay-validation
plan: 03
subsystem: ML Calibration
tags: [calibration, v2.11-dependency, counterfactual, pre-flight]
dependency_graph:
  requires: [127-01, 127-02]
  provides: [SC-05-deferral-record]
  affects: []
tech_stack:
  added: []
  patterns: [pre-flight-gate, blocker-surfacing]
key_files:
  created: [docs/plans/phase-127-calibration-retrain-log.md]
  modified: []
decisions:
  - SC-05 DEFERRED to v2.11 by design — counterfactual_pnl_r is the calibration target and is 100% NULL this phase
  - Plan 03 premise corrected: trade_executions is NOT empty (lifecycle replay populates actual_pnl_r); blocker is target-wiring, not data absence
metrics:
  completed_date: "2026-06-17"
---

# Phase 127 Plan 03: Calibration Retrain Pre-Flight Summary

## Objective
Surface the calibration-retrain dependency on v2.11. Pre-flight the ml-training target;
confirm no populated calibration outcome; record the blocker. Do NOT retrain on an absent
target.

## Outcome: RETRAIN NOT TRIGGERED — SC-05 DEFERRED to v2.11 (by design)

### Pre-flight results (verbatim)
- **(a) migration gap:** `ml_training_agent.py` has no `signal_outcomes`/`signal_ledger_full` refs — clean.
- **(b) calibration target:** `trade_frames.counterfactual_pnl_r` via `training_data.py:45,58`
  (`sl.counterfactual_pnl_r AS pnl_r`, filtered `IS NOT NULL`).
- **(c) target population:** `counterfactual_pnl_r` = **0 non-null / 1,036,513** → calibrator
  selects 0 rows. Retrain would learn nothing.

### Trigger decision
**Not triggered.** No `systemctl start indicagent-ml-training.service`. Rationale: target
all-NULL.

## Premise correction (rigor note)
The plan assumed `trade_executions` would be empty. In the rebuild corpus it is **not** —
`lifecycle_replay` populates `actual_pnl_r` (989,502 non-null / 1,063,798; exit_reasons
fully distributed). The blocker therefore stands for a sharper reason: an outcome *exists*
(`actual_pnl_r`) but the ML calibrator is wired to `counterfactual_pnl_r`, which only
CounterfactualTracker (v2.11) populates.

**Triage flag for v2.11:** whether ML should train on the now-available `actual_pnl_r`
instead of/in addition to `counterfactual_pnl_r` is a v2.11 design decision (surfaced, not
acted on).

## Input corpus stats
| Metric | Value |
|--------|-------|
| signal_events | 1,036,513 |
| trade_frames | 1,036,513 |
| trade_executions | 1,063,798 |
| counterfactual_pnl_r non-null | 0 |
| actual_pnl_r non-null | 989,502 |
| setup_performance rows | 0 (wiped, not refreshed) |

## Corpus ML-readiness
Clean corpus in place. Once v2.11 populates `counterfactual_pnl_r`, calibration runs with
**no second replay**.

## Deliverable
`docs/plans/phase-127-calibration-retrain-log.md` — full pre-flight output, trigger decision,
dependency chain, SC-05 status, and the premise correction.

## Self-Check: PASSED
- All three pre-flight outputs recorded verbatim
- Trigger decision (not triggered) with rationale
- SC-05 marked DEFERRED to v2.11
- setup_performance stale/empty state recorded
- No silent corrupt retrain under any branch
