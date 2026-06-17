---
phase: 127-clean-replay-validation
plan: 02
subsystem: Signal Validation
tags: [validation, integrity, context-features, ctf, v2.11]
dependency_graph:
  requires: [127-01]
  provides: [phase-127-validation-report]
  affects: []
tech_stack:
  added: [production/scripts/phase_127_report.py (deferred — report written from direct queries)]
  patterns: [measure-and-name, no-proxy-for-target]
key_files:
  created: [docs/plans/phase-127-validation-report.md]
  modified: []
decisions:
  - Corpus structurally clean (0 orphans, sha256 IDs) but context_features/ctf_score 100% NULL — top open finding
  - Signal quality NOT measured (no counterfactual outcome; v2.11 dependency) — deferred, not faked
  - REBUILD_STATUS=FAILED is a post-commit assertion crash; data intact
metrics:
  completed_date: "2026-06-17"
---

# Phase 127 Plan 02: Validation Report Summary

## Outcome
Validation report delivered: `docs/plans/phase-127-validation-report.md`. Measures what is
measurable; names what is not (no proxy for signal quality on a no-outcome corpus).

## Measured — PASS
- **Integrity:** 0 orphan signal_events, 0 orphan trade_frames. 1,036,513 distinct signal_ids.
- **Determinism:** signal_id = sha256[:32] (version nibble uniform 0-f, not uuid4); frame_id
  = uuid5 (100% version '5'). Resolves the replay-architecture uuid4 concern (memory updated).

## Measured — SURFACED (not papered over)
- **⚠️ HEADLINE: `context_features` and `ctf_score` are 100% NULL** (1,036,513/1,036,513).
  Every signal is cold-start with no ECL/CTF annotation. SC-02 coverage is vacuous (zero
  non-cold-start). Contradicts the warmup-noop memory's "single cold pass produces valid CTF"
  claim and the checklist's "ctf NULL should be ~0". Root cause open: write-path gap vs
  cold-start-not-handled. **Blocks context-conditional ML until resolved.** Persistent
  pattern (pre-rebuild baseline showed the same).
- **~42% signals still `pending`** (431,442) — 431,719 frames have 0 executions. Lifecycle
  replay reached ~58% to `expired`. Confirm whether 42% pending is expected or a short-run.
- **6 of 36 setups emitted zero signals** — possible emission-gate coverage gaps (checklist #8).
- **201,149 plugin errors on rolled-month contracts** (NQU6/YMM6/RTYM6) — non-fatal; checklist #1.
- **`REBUILD_STATUS=FAILED` is misleading** — Stage 2 committed cleanly, then crashed in the
  post-insert integrity assert on a transient DB connection drop. Data verified intact.

## Named — NOT measured (correctly)
- **Signal quality / edge / calibration** — no `counterfactual_pnl_r` outcome (v2.11; Plan 03).
  No fire-rate proxy substituted for edge.

## Key corpus stats
| Metric | Value |
|--------|-------|
| signal_events / trade_frames / trade_executions | 1,036,513 / 1,036,513 / 1,063,798 |
| context_features coverage | 0.000% (100% cold-start) |
| ctf_score non-null | 0 |
| counterfactual_pnl_r non-null | 0 (v2.11) |
| actual_pnl_r non-null | 989,502 (lifecycle branch; 2/frame = bracket, not dup) |
| signals terminal (`expired`) | 604,252 (58%) |
| setups firing | 30 / 36 |

## Deliverable
`docs/plans/phase-127-validation-report.md` — full report + RCA Part VI + prioritized
follow-ups. Top follow-up: root-cause the 100% NULL context_features/ctf_score.

## Self-check: PASSED
- Integrity + determinism measured (PASS).
- context_features/ctf NULL surfaced, not papered over.
- Signal quality correctly not measured; no proxy substituted.
