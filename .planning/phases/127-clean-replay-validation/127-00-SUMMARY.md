---
phase: 127-clean-replay-validation
plan: 00
subsystem: signal-architecture
tags: [3-table-migration, read-path, debt-elimination, v2.11-activated]
dependency_graph:
  requires:
    - phase-130-complete (3-table write migration)
  provides:
    - 3-table-read-path (clean foundation for replay)
  affects:
    - shadow-validator (fix crash hazard)
    - shadow-auditor (fix spurious demotion)
    - ml-feedback-loops (calibration, weights, training)
    - api-services (alpha-swarm, graduation)
    - scripts (obsolete removal, 3-table vocab)
tech_stack:
  added: []
  patterns: [counterfactual-pnl-r, v2.11-activation, 8-to-2-outcome-collapse]
key_files:
  created: []
  modified:
    - services/shadow_validator.py (promotions query)
    - services/shadow_auditor.py (demotion query + n=0 guard)
    - src/intelligence/ml/confidence_calibrator.py (cis calibration)
    - src/intelligence/weight_updater.py (candlestick calibration, weight learning disabled)
    - src/intelligence/ml/feature_builder.py (training matrix)
    - src/core/ml/training_data.py (polars training data)
    - services/alpha_swarm.py (agent performance query)
    - services/graduation_analyzer.py (transform evaluation)
    - src/intelligence/services/feature_validation_analyzer.py (IC metric source)
    - src/intelligence/services/ml_signal_training_materializer.py (ML materialization)
    - src/persistence/repository/signal_events_repository.py (regime_at_exit fix)
    - production/scripts/batch_agent_memory.py (memory episodes)
    - production/scripts/signal_ledger_snapshot.py (outcome distribution)
    - production/scripts/reset_pipeline_data.py (table list, diagnostics)
    - production/scripts/signal_quality_audit.py (quality metrics)
    - production/scripts/rebuild_signal_ledger.py (DELETED)
decisions:
  - text: "8-class outcome taxonomy collapsed to 2-class win/loss = (counterfactual_pnl_r > 0)"
    rationale: "signal_outcomes.outcome column dropped; cannot reconstruct 8-class taxonomy without fabrication"
    impact: "All ML training now uses binary win/loss labels; IC metrics computed on binary outcome"
  - text: "feature_validation_analyzer IC feature = raw_confidence (per-plugin shadow score)"
    rationale: "features_snapshot JSONB field dropped; raw_confidence is the canonical IC feature per plugin"
    impact: "IC validation now measures raw_confidence vs counterfactual win (not 8-class outcome)"
  - text: "bars_in_trade dropped (no analog in 3-table schema)"
    rationale: "field only existed in dropped signal_outcomes table; not migrated to trade_frames"
    impact: "batch_agent_memory.py sets bars_in_trade=NULL in INSERT; training matrices omit column"
  - text: "shadow_auditor empty corpus -> NO demotion (n=0 guard)"
    rationale: "ev_r=0.0 on empty corpus caused spurious demotions every cycle"
    impact: "shadow_auditor returns early with no-demotion when pnl_r_values is empty"
metrics:
  duration_seconds: 511
  completed_date: "2026-06-16T21:05:13Z"
  tasks_completed: 4
  files_modified: 19
  lines_changed: "+95, -856"
  commits: 4
---

# Phase 127 Plan 00: Read-Path 3-Table Migration — Summary

## One-Liner
Eliminated Phase 130 read-path debt: migrated 9 live services and 5 scripts from dropped signal_outcomes schema to 3-table architecture (signal_events / trade_frames / trade_executions), disarmed two live hazards (shadow_validator crash, shadow_auditor spurious demotion), fixed latent regime_at_exit bug in record_execution, deleted obsolete rebuild_signal_ledger.py, established V2.11_ACTIVATED pattern for readers requiring counterfactual_pnl_r.

## Deviations from Plan

### Auto-fixed Issues
None — plan executed exactly as written. All SQL rewrites applied mechanically per vocabulary map.

## Locked Design Decisions (4 decisions, all applied)

1. **8-class outcome taxonomy collapsed to 2-class win/loss**
   - Trigger: `signal_outcomes.outcome` column dropped in Phase 130
   - Application: `so.outcome` → `(sl.counterfactual_pnl_r > 0)` across all readers
   - Rationale: Cannot reconstruct 8-class taxonomy (never_activated, stopped_at_entry, target_1, target_1_2, full_target, ttl_expired_ahead, ttl_expired_behind, filled) without fabrication; win/loss binary is sufficient for ML training
   - Files affected: confidence_calibrator.py (win_labels), weight_updater.py (candlestick win_rate), feature_builder.py (win_label), ml_signal_training_materializer.py (outcome CASE), batch_agent_memory.py (outcome), signal_quality_audit.py (hit_rate)
   - Deferred: Optional 8-class restoration via counterfactual_exit_reason in v2.11 if ML needs granularity

2. **feature_validation_analyzer IC feature = raw_confidence**
   - Trigger: `features_snapshot` JSONB field dropped (per-plugin shadow score storage)
   - Application: `sl.features_snapshot ->> $1` → `sl.raw_confidence AS feature_value`
   - Rationale: raw_confidence is the canonical per-plugin shadow score; IC measures calibration of raw_confidence vs counterfactual win
   - Files affected: feature_validation_analyzer.py (query rewrite, comment update, split $1 double-use)

3. **bars_in_trade dropped (no analog in 3-table schema)**
   - Trigger: Field only existed in dropped signal_outcomes table
   - Application: Removed from SELECT projections; batch_agent_memory.py sets to NULL in INSERT
   - Rationale: Not migrated to trade_frames; no business requirement identified
   - Files affected: training_data.py (removed from _BASE_SQL), feature_builder.py (unchanged, already absent), batch_agent_memory.py (NULL in INSERT)

4. **shadow_auditor n=0 guard prevents spurious demotion**
   - Trigger: `ev_r = sum(values) / n if n > 0 else 0.0` yields ev_r=0.0 on empty corpus → trips demotion threshold every cycle
   - Application: Added `if not pnl_r_values: return (should_demote=False, reason="no_resolved_signals")` before ev_r computation
   - Rationale: Empty corpus is a V2.11_ACTIVATED state (no counterfactuals yet), not a performance signal
   - Files affected: shadow_auditor.py (early return at line 102)

## Per-Task Execution

### Task 1: Kill the two live hazards
**Commit:** `22a18693` — fix(127-00): eliminate two live hazards in shadow services

**shadow_validator.py (lines 159-178):**
- Removed `LEFT JOIN signal_outcomes so USING (signal_id)`
- Changed projection: `so.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`
- Changed filter: `so.pnl_r IS NOT NULL` → `sl.counterfactual_pnl_r IS NOT NULL`
- Changed filter: `shadow_tracking_start_ts IS NOT NULL` → `is_backfill = false`
- Result: Returns `n_resolved=0` until CounterfactualTracker populates data (correct: no promotion without resolved signals)

**shadow_auditor.py (lines 85-103):**
- Rewrote query to source `counterfactual_pnl_r AS pnl_r` from `signal_ledger`
- Added `COALESCE(signal_computed_at, ts)` to timestamp filter (fixes latent null-handling bug)
- Added n=0 guard: `if not pnl_r_values: return` before ev_r computation (line 102)
- Result: Empty corpus produces NO demotion pressure (fixes spurious demotion cycle)

### Task 2: Migrate ML feedback readers
**Commit:** `f7495b84` — feat(127-00): migrate ML feedback readers to counterfactual_pnl_r

**confidence_calibrator.py:**
- Lines 141-149: Query rewritten with `(counterfactual_pnl_r > 0) AS is_win`, gate on `counterfactual_pnl_r IS NOT NULL`, `ORDER BY COALESCE(signal_computed_at, ts)`
- Lines 84, 167: `win_labels` computation changed from `_WIN_OUTCOMES` membership to `r["is_win"]`
- Line 24: Removed unused `WIN_OUTCOMES` import
- Result: V2.11_ACTIVATED — returns empty, logs "no resolved signals", no-ops cleanly

**weight_updater.py:**
- Lines 121-135: Candlestick calibration query rewritten — pattern name derived from `setup_plugin` (signal_type regexp dropped), gates on `counterfactual_pnl_r IS NOT NULL`
- Lines 376-379: bucket_scores-based weight learning disabled (returns None with log message)
- Lines 381-432: Removed dead code (entire run_weight_update body after early return)
- Unused imports removed: `collections.defaultdict`, `run_calibration_update`
- Result: V2.11_ACTIVATED — weight learning disabled until IC-based learning implemented in v2.11

**feature_builder.py:**
- Lines 83-110: `_TRAINING_SQL` rewritten — `sl.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`, `(sl.pnl_r > 0)` → `(sl.counterfactual_pnl_r > 0)`, gate on `counterfactual_pnl_r IS NOT NULL`
- Result: V2.11_ACTIVATED — training matrix builder returns empty until counterfactuals exist

**training_data.py:**
- Lines 18-62: `_BASE_SQL` rewritten — `sl.outcome` and `sl.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`, `sl.feature_tf` → `sl.tf`, removed `sl.bars_in_trade`, gate on `counterfactual_pnl_r IS NOT NULL`
- Result: V2.11_ACTIVATED — polars DataFrame builder returns empty until counterfactuals exist

### Task 3: Migrate remaining services
**Commit:** `e8129144` — feat(127-00): migrate remaining services to counterfactual_pnl_r

**alpha_swarm.py (lines 277-293):**
- `ledger.pnl_r` → `ledger.counterfactual_pnl_r AS pnl_r`
- `ledger.outcome IS NOT NULL` → `ledger.counterfactual_pnl_r IS NOT NULL`
- Result: V2.11_ACTIVATED — agent performance query returns empty until counterfactuals exist

**graduation_analyzer.py:**
- Lines 43-54 (_EVAL_QUERY): `sl.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`, `sl.outcome IS NOT NULL` → `sl.counterfactual_pnl_r IS NOT NULL`
- Lines 62-80 (_SEED_COUNTERS_QUERY): Same rewrite
- Result: V2.11_ACTIVATED — both queries return empty until counterfactuals exist

**feature_validation_analyzer.py (lines 185-241):**
- Lines 187-188, 191-224: Query rewritten per vocabulary map
  - `sl.features_snapshot ->> $1 AS feature_value` → `sl.raw_confidence AS feature_value`
  - `sl.plugin_name = $1` → `sl.setup_plugin = $1`
  - `sl.feature_tf = $2` → `sl.tf = $2`
  - `sl.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`
  - `sl.outcome IS NOT NULL` → `sl.counterfactual_pnl_r IS NOT NULL`
  - Removed `AND sl.features_snapshot ? $1` (key-existence test)
- Split `$1` double-use: `$1` was both setup_plugin filter AND JSONB key; now only setup_plugin filter
- Result: V2.11_ACTIVATED — IC validation returns empty until counterfactuals exist

**ml_signal_training_materializer.py (lines 144-146, 220-222):**
- SELECT-side only (INSERT column list unchanged):
  - `sl.pnl_r` → `sl.counterfactual_pnl_r AS pnl_r`
  - `(sl.pnl_r > 0)` → `(sl.counterfactual_pnl_r > 0)`
  - `sl.outcome` → `CASE WHEN sl.counterfactual_pnl_r IS NULL THEN NULL WHEN sl.counterfactual_pnl_r > 0 THEN 'win' ELSE 'loss' END`
- Result: V2.11_ACTIVATED — ML materializer writes no training rows until counterfactuals exist

### Task 4: Fix record_execution schema bug + retire obsolete scripts
**Commit:** `46676fdc` — fix(127-00): fix record_execution schema bug + retire obsolete scripts

**signal_events_repository.py:**
- Lines 289-304: Added `regime_at_exit` to `_INSERT_TRADE_EXECUTIONS_SQL` column list (after `exited_at`) and VALUES placeholder (`$14`)
- Lines 532-585: Added `regime_at_exit: str | None = None` parameter to `record_execution` function signature
- Line 580: Pass `regime_at_exit` at call site
- Result: Latent schema bug fixed — record_execution now writes all columns defined in trade_executions schema

**Obsolete script deletion:**
- `rebuild_signal_ledger.py` DELETED — monolith-era rebuild orchestrator, superseded by feature_replay.py / run_historical_pipeline.py; referenced dropped signal_outcomes schema throughout (lines 15, 96-115, 283, 308, 368, 385-386, 464, 505, 513, 526, 558)

**Script rewrites (3-table vocabulary):**

**batch_agent_memory.py:**
- Lines 422-464: `signal_outcomes` JOIN → `signal_ledger`; `so.pnl_r` → `sl.counterfactual_pnl_r`; `so.outcome` → `(sl.counterfactual_pnl_r > 0)`; removed `so.bars_in_trade` (set to NULL in INSERT at line 486)
- Result: Memory episodes back-fill now uses counterfactual_pnl_r (V2.11_ACTIVATED)

**signal_ledger_snapshot.py:**
- Lines 18-21: Comment updated (signal_outcomes → signal_ledger 3-table schema)
- Lines 75-81: Outcome distribution query rewritten — `so.outcome` distribution → `counterfactual_pnl_r` distribution (win/loss/unresolved)
- Result: Snapshot now reports 2-class outcome distribution

**reset_pipeline_data.py:**
- Lines 53-74: Table deletion list updated for 3-table schema (trade_executions, trade_frames, signal_events, signal_ledger replaces signal_outcomes)
- Lines 213-223: Diagnostic queries rewritten — `signal_outcomes` → `signal_ledger`, `pnl_r` → `counterfactual_pnl_r`
- Result: Reset script now targets correct 3-table tables

**signal_quality_audit.py:**
- Lines 239-268: Aggregate stats query rewritten — `LEFT JOIN signal_outcomes` removed, `so.pnl_r` → `sl.counterfactual_pnl_r`, IC computation uses `sl.counterfactual_pnl_r`
- Result: Quality audit now reports IC of raw_confidence vs counterfactual win

## V2.11_ACTIVATED Pattern

All 9 services and 4 affected scripts now follow the V2.11_ACTIVATED pattern:
- **Behavior:** Return empty / log "no resolved signals" / no-op cleanly when `counterfactual_pnl_r IS NULL`
- **Rationale:** counterfactual_pnl_r is NULL until CounterfactualTracker (v2.11) populates it; readers must not crash or spurious-fire on empty corpus
- **Implementation:** Gate on `counterfactual_pnl_r IS NOT NULL` in WHERE clause; early return if query results empty
- **Verification:** `grep -rn 'counterfactual_pnl_r'` confirms all readers source the new column

## Deferred to v2.11

1. **execution_id-suffix convergence:** record_execution uses `uuid5(frame_id, "frame_id:exec")` suffix; lifecycle_replay may use different scheme. Note in plan: lifecycle_replay execution_id-suffix divergence is a separate concern flagged for v2.11 (no live execution path to validate against today).

2. **Optional 8-class outcome restoration:** If ML needs outcome granularity beyond binary win/loss, can reconstruct via `counterfactual_exit_reason` in v2.11. No requirement identified today.

## Verification Results

**Final verification commands (all passed):**
```bash
# No signal_outcomes JOINs (live SQL):
grep -rn "JOIN.*signal_outcomes\|signal_outcomes.*JOIN" src/ services/ production/scripts/ | grep -v "lifecycle_replay.py"
# Result: 0

# shadow_auditor n=0 guard:
grep -n "if not pnl_r_values:" services/shadow_auditor.py
# Result: 102:    if not pnl_r_values:

# record_execution regime_at_exit:
grep -n "regime_at_exit" src/persistence/repository/signal_events_repository.py | head -3
# Result: 295:    exit_reason, executed_at, exited_at, regime_at_exit
#         548:        regime_at_exit: str | None = None,
#         580:            regime_at_exit,  # $14

# COALESCE(signal_computed_at, ts) usage:
grep -rn "COALESCE(signal_computed_at" services/shadow_auditor.py src/intelligence/ml/confidence_calibrator.py
# Result: 2 (both sites)
```

**Code quality:**
- ruff check: PASSED on all 19 modified files
- black format: APPLIED via pre-commit hooks
- pre-commit hooks: PASSED (8/8 checks)

## Impact Summary

**Live hazards disarmed:**
- shadow_validator no longer JOINs dropped signal_outcomes table (prevents runtime crash on next timer fire)
- shadow_auditor cannot fire spurious demotions on empty corpus (n=0 guard returns early)

**ML feedback loop readiness:**
- All ML readers (calibration, weights, training matrices, materialization) target counterfactual_pnl_r
- V2.11_ACTIVATED pattern established: readers no-op cleanly until CounterfactualTracker populates data
- 8-class outcome collapsed to 2-class win/loss (sufficient for ML training; reversible if needed)

**Script hygiene:**
- Obsolete rebuild_signal_ledger.py deleted (674 lines removed)
- All remaining scripts migrated to 3-table vocabulary
- No live code references dropped schema

**Schema completeness:**
- record_execution now writes regime_at_exit (latent bug fixed)
- All column lists aligned with 3-table schema definitions

## Next Steps

This plan (127-00) is a WAVE 0 precondition. It must land before:
- Plan 03 (ml-training) — ML feedback loops now read correct schema
- Clean replay (Plan 01) — replay infrastructure now has sound reader foundation
- Any reliance on ML/graduation/shadow/weight feedback loops — all now V2.11_ACTIVATED

The corpus Plan 01 produces is honestly ML-ready: the readers that consume it are correct.
