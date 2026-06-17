# Phase 127 Plan 00 — execute the read-path 3-table migration

Branch: `phase-127/00-read-path-3table-migration` (created, planning committed).

The full spec is in `.planning/phases/127-clean-replay-validation/127-00-PLAN.md` (4 tasks, exact SQL rewrites per site). Four design decisions are LOCKED in the plan's critical_corrections. Execute in task order — Task 1 (the two live hazards) first.

## Execution checklist (in priority order)
- [ ] **Task 1 — live hazards (DO FIRST):**
  - [ ] `services/shadow_validator.py:162-178` — drop `LEFT JOIN signal_outcomes`; read `counterfactual_pnl_r` off view; `shadow_tracking_start_ts` -> `is_backfill = false`
  - [ ] `services/shadow_auditor.py:86-97` — source `counterfactual_pnl_r`, `COALESCE(signal_computed_at, ts)`, **add explicit n=0 no-demotion guard** before ev_r
- [ ] **Task 2 — ML feedback readers:** confidence_calibrator.py:141-149 (+consumers ~84/~167, drop _WIN_OUTCOMES membership), weight_updater.py:124-141 & :383-391 (signal_type->setup_plugin, bucket_scores->raw_confidence), feature_builder.py:83-110, training_data.py:18-62 (drop bars_in_trade)
- [ ] **Task 3 — remaining services:** alpha_swarm.py:277-293, graduation_analyzer.py:43-54 & :62-80, feature_validation_analyzer.py:185-241 (IC feature->raw_confidence, split $1 double-use), ml_signal_training_materializer.py:144-146 & :220-222 (SELECT-side only; leave EXCLUDED.*/INSERT cols)
- [ ] **Task 4 — record_execution + scripts:** signal_events_repository.py:289-304/+532-585 (add regime_at_exit); retire/rewrite rebuild_signal_ledger.py, reset_pipeline_data.py, signal_quality_audit.py, batch_agent_memory.py, signal_ledger_snapshot.py
- [ ] Verify: `grep -rn "signal_outcomes" src/ services/ production/scripts/` = 0 live hits; `.venv/bin/pytest tests/unit/ -q` green; ruff/black clean
- [ ] Per Done-Coding SOP: code-simplifier -> /review -> pytest -> commit -> merge main -> delete branch -> prune -> push
- [ ] Write 127-00-SUMMARY.md

## Locked design decisions (do not re-litigate)
1. Outcome 8-class -> 2-class win/loss = `(counterfactual_pnl_r > 0)`.
2. feature_validation_analyzer IC feature = `raw_confidence`.
3. `bars_in_trade` dropped (no analog).
4. shadow_auditor empty corpus -> NO demotion (n=0 guard).

## Deferred to v2.11 (note in SUMMARY, do not fix now)
- execution_id-suffix convergence between record_execution and lifecycle_replay.
- Optional 8-class outcome restoration via counterfactual_exit_reason.

## False positives (do NOT change)
- feature_builder.py `tf_sig.value->'features_snapshot'` (JSONB-array source).
- ml_signal_training_materializer.py EXCLUDED.*/INSERT cols (target table ml_signal_training).
- signal_events_repository.py frame_details JSONB writes.

## Why
Phase 130 migrated write paths but left read paths pointing at dropped schema; shadow_validator crashes on its timer and shadow_auditor spuriously demotes every cycle. This is the debt Plan 00 eliminates as a wave-0 precondition to the clean replay.
