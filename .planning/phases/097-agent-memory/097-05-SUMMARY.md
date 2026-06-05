---
phase: 097-agent-memory
plan: "05"
subsystem: agent-memory
tags: [memory, calibration, batch, systemd, statistics]
dependency_graph:
  requires: ["097-01", "097-02", "097-03", "097-04"]
  provides: ["memory_batch.py nightly 4-step orchestrator", "indicagent-memory-batch timer/service"]
  affects: ["memory_episodes_labeled", "memory_calibration_promoted", "memory_regime_transitions", "memory_calibration_spc"]
tech_stack:
  added: []
  patterns: ["circular block bootstrap (D-15)", "BH-FDR correction", "Brier decomposition", "EWMA/CUSUM SPC"]
key_files:
  created:
    - production/scripts/memory_batch.py
    - production/systemd/indicagent-memory-batch.service
    - production/systemd/indicagent-memory-batch.timer
  modified:
    - services/service_auditor.py
decisions:
  - "HMM regime integer 0/1/2 maps to ranging/trending_up/trending_down via _HMM_REGIME_LABEL dict; derived from core/ml/features.py canonical convention"
  - "UNIQUE INDEX WHERE ts_end IS NULL on memory_regime_transitions prevents double-open; INSERT uses ON CONFLICT ON CONSTRAINT mem_reg_open DO NOTHING"
  - "Circular block bootstrap block length formula: max(5, round(N^(1/3))) per Hall & Horowitz (1996) — documented in code as D-15 requirement"
metrics:
  duration: "5m 36s"
  completed_date: "2026-06-05"
  tasks_completed: 2
  files_changed: 4
---

# Phase 097 Plan 05: Memory Batch Nightly Orchestrator Summary

**One-liner:** 4-step nightly batch orchestrator (epoch detection, regime transitions, episode backfill, N>=30-gated calibration promotion with BH-FDR + circular block bootstrap) plus systemd 21:00 timer and _DAG_ORDER registration.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Implement memory_batch.py 4-step orchestrator | e8157c3f | production/scripts/memory_batch.py |
| 2 | Create systemd units and register in service_auditor | 15770cfd | production/systemd/indicagent-memory-batch.{service,timer}, services/service_auditor.py |

## What Was Built

### Task 1: memory_batch.py

Four-step orchestrator; step N failure aborts N+1+ and returns non-zero exit:

**Step 1 EpochJob (job="memory-epoch"):** Queries `memory_calibration_spc` for cohorts where the last 3 rows all have `ks_alarm=TRUE`. Auto-increments `memory_system_state.current_regime_epoch` once when any cohort triggers (prevents staleness during high-volatility operator delay). Manual override path preserved.

**Step 2 RegimeTransitionJob (job="memory-regime"):** Reads `signal_ledger_full` for current `hmm_regime_at_fire` per `(symbol, feature_tf)`. Converts integer (0=ranging, 1=trending_up, 2=trending_down) to `memory_regime_label` ENUM. Closes open rows with `ts_end`, computes `win_rate` (NULL when `signal_count < 30`), `transition_probs` (NULL when `transition_n < 30`, must sum to 1.0 +/- 0.001 per `chk_transition_probs_sum`). Opens new row per `(symbol, timeframe)` via `ON CONFLICT ON CONSTRAINT mem_reg_open DO NOTHING`.

**Step 3 BackfillJob (job="memory-backfill"):** JOINs `signal_outcomes` to `memory_episodes_raw` on `signal_id WHERE embedding IS NOT NULL AND outcome IS NULL AND so.outcome IS NOT NULL`. INSERTs into `memory_episodes_labeled` with `ON CONFLICT (id, ts) DO NOTHING` (idempotent). Separately back-fills `n_eligible` (C-02) from `market_data_ohlcv + signal_ledger_full`. Emits `memory_episodes_labeled` gauge with post-run count.

**Step 4 PromotionJob (job="memory-promote"):** Groups `memory_episodes_labeled` by `(agent_id, symbol, hmm_regime, entry_type, regime_epoch)` with `HAVING COUNT(*) >= 30`. F6 guard: skips cohorts with >20% NULL `n_eligible`, increments `memory_promotion_skipped_n_eligible` counter. Computes: Brier decomposition, IC + t-stat + p-value, calibration error, correction factor (only when stable across 3 rolling sub-windows), circular block bootstrap CI (block_len = max(5, round(N^1/3)) -- D-15). Applies BH-FDR across all surviving cohorts. C-04 feedback-loop test (two-proportion Z-test, quarantines when p < 0.05, sets `quarantine_review_at = now + 7d`). Writes to `memory_calibration_promoted` (append-only) and SPC row to `memory_calibration_spc`. Emits `memory_cohorts_promoted_total`, `memory_cohorts_quarantined_total`, `memory_promotion_skipped_n_eligible` counters.

All steps emit `job_completed_total{job, status}`. `flush_and_shutdown_metrics()` called in `finally` block (oneshot OTLP drain contract).

### Task 2: Systemd + Service Registry

- `indicagent-memory-batch.service`: Type=oneshot, User=bg, WorkingDirectory=/home/bg/dev/indicagent, TimeoutStartSec=600, After/Requires indicagent-infrastructure.target
- `indicagent-memory-batch.timer`: OnCalendar=*-*-* 21:00:00 (9pm, before ml-training 23:00), Persistent=true
- `services/service_auditor.py`: added to `_DAG_ORDER` at priority 8 alongside other nightly oneshots; added to `_ONESHOT_UNITS` with D-06 job names documented in comment

## Verification

- `memory_batch.py --dry-run` completes against live DB with empty memory tables; all 4 steps logged; exit code 0
- `ruff check production/scripts/memory_batch.py` passes
- Timer contains `21:00:00`; service registered in `_DAG_ORDER` and `_ONESHOT_UNITS`
- `python -c "import ast; ast.parse(...)"` on service_auditor.py: parse ok
- `systemd-analyze verify`: no errors

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed HMM regime column name mismatch**
- **Found during:** Task 1 dry-run verification
- **Issue:** Plan spec referenced `hmm_state` column but signal_ledger_full uses `hmm_regime_at_fire` (integer 0/1/2)
- **Fix:** Updated query to use `hmm_regime_at_fire`, added `_HMM_REGIME_LABEL` mapping dict (0=ranging, 1=trending_up, 2=trending_down from core/ml/features.py), added validation with skip on unknown values
- **Files modified:** production/scripts/memory_batch.py
- **Commit:** e8157c3f

## Self-Check: PASSED

| Item | Status |
|------|--------|
| production/scripts/memory_batch.py | FOUND |
| production/systemd/indicagent-memory-batch.service | FOUND |
| production/systemd/indicagent-memory-batch.timer | FOUND |
| Commit e8157c3f (Task 1) | FOUND |
| Commit 15770cfd (Task 2) | FOUND |
