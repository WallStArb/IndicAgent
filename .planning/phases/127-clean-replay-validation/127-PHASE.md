---
phase: 127-clean-replay-validation
phase_number: 127
status: planning
created: 2026-06-16T14:15:00Z
updated: 2026-06-16T14:15:00Z
---

# Phase 127: Clean Replay + Validation

## Objective

Run full historical replay on corrected v2.10 pipeline with --warmup. Generate validation report using correct methodology (no cross-population statistics; firing rate = emission frequency). Update RCA Part VI with measured values. **Calibration curve retraining is DEFERRED to v2.11** (the replay corpus has no PnL outcome target until CounterfactualTracker populates `counterfactual_pnl_r`).

## Context

v2.10 phases 123-130 are complete on the WRITE path (signal_events + trade_frames - verified correct, atomic, deterministic frame_ids). **The READ path migration was NOT finished by Phase 130** - ~9 live src/services readers and several scripts still query the dropped `signal_outcomes` table and absent `signal_ledger` view columns. Two are live hazards (`shadow_validator` JOINs the dropped table; `shadow_auditor` triggers spurious demotions on an empty corpus). **Plan 00 (wave 0) closes this gap as a precondition** - it must land before Plan 03 (ml-training) and before any reliance on the ML/graduation/shadow/weight feedback loops. Only with Plan 00 done is the "ML-ready corpus" claim honest.

**Plan DAG:**
- 00 (read-path migration) - wave 0/1, independent
- 01 (clean replay) - wave 1, independent of 00 (write path already clean); backgrounded, hours
- 02 (validation report) - wave 2, depends on 01
- 03 (ml-training pre-flight) - wave 3, depends on 00 + 01 + 02

**Key Changes in v2.10:**
- ECL boundary (Phase 123) - emission suppressors removed
- Cold-start hardening (Phase 124) - NULL context_features handled
- APR migration (Phase 125) - all constants externalized
- Confluence wiring (Phase 126) - all plugins emit CTF
- 3-table schema (Phase 128-130) - signal_events/trade_frames/trade_executions (write path complete; read path closed by Plan 00)

## Success Criteria

**What Phase 127 CAN verify (plumbing + structure):**
1. Clean replay completes without errors, deterministically, integrity intact (zero orphans)
2. `context_features` coverage > 99% for non-cold-start signals - this is a DATA COMPLETENESS gate (missing features = broken plumbing), not a signal-quality judgment
3. Emission fire rate is MEASURED and REPORTED as a distribution per setup_plugin (`100 * signals / intelligence_features bar-instances`, D6 methodology). It is NOT a pass/fail gate. The only structural claim it supports: the Phase 124 onset_guard leak (pre-fix 15-30% of bars) is closed. A valid signal firing at 10% with edge is fine; a 0.5% signal without edge is not - fire rate alone says nothing about quality.
4. Validation report uses correct methodology: NO Welch's t-test (populations not exchangeable), NO calibration correlation (no outcome target exists), fire rate reported descriptively not gated

**What Phase 127 CANNOT verify (deferred to v2.11):**
5. **Signal EDGE / predictive value** - the actual definition of signal success. Requires a PnL outcome target. Neither candidate exists in the replay corpus: `counterfactual_pnl_r` is NULL by design (CounterfactualTracker is v2.11) and `trade_executions` is unpopulated by replay. This is the load-bearing gap and the report must name it explicitly rather than substituting an arbitrary fire-rate percentage.
6. **Calibration retrain** - deferred to v2.11 for the same reason (no target). Plan 03 surfaces the blocker; it does not retrain on empty/NULL targets.
7. RCA Part VI updated with MEASURED values (and explicit acknowledgement that edge measurement is deferred)

## Constraints

- Schema: 3-table (signal_events/trade_frames/trade_executions). Join chain for execution-layer data: `signal_events.signal_id` -> `trade_frames.signal_id`, then `trade_frames.frame_id` -> `trade_executions.frame_id`. `trade_executions` has NO `signal_id` column.
- Methodology: No cross-population statistics (see RESEARCH.md Issue 1). Firing rate = emission frequency (see RESEARCH.md Issue 7).
- Outcome data: NONE in replay corpus (see RESEARCH.md Issue 4). Calibration cannot be measured or retrained this phase.
- Data integrity: No orphaned records, >99% context_features coverage
- Determinism: Replay must be reproducible

## Artifacts

- RESEARCH.md (methodology resolution - 10 issues)
- CONTEXT.md (adapted requirements)
- 127-00-PLAN.md (wave 0: read-path 3-table migration + debt retirement)
- 127-01-PLAN.md (before-snapshot + clean replay)
- 127-02-PLAN.md (outcome-free validation report)
- 127-03-PLAN.md (calibration deferral to v2.11)
