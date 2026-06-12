---
name: project-backfill-signal-integrity
description: Backfill signal integrity fix — design complete, plan written, ready to execute
metadata:
  type: project
---

Design and plan complete as of 2026-06-06. Ready to execute.

**Why:** 280k stacked signals from multiple uuid4 backfill runs. make_signal_id() (deterministic SHA-256) already shipped. DB is dirty — needs --clean + replay. Two structural gaps also being fixed.

**Corruption confirmed:**
- ESM6/1m: 13,480 bars with 2 was_selected=TRUE winners (50% of bars)
- ESM6/15m: 1,315 bars with up to 3 winners
- calibration_curves and setup_performance tables both empty (no-op today, structural fix for future)

**Plan location:** `docs/plans/2026-06-06-backfill-signal-integrity-plan.md`

**Design doc:** `docs/plans/2026-06-06-backfill-signal-integrity.md`

**6 tasks — all changes to `production/scripts/run_historical_pipeline.py` only:**
1. Add `_load_calibration_curves(conn, symbol="*")` + `_load_perf_weights(conn)` — new loader functions. calibration uses 2-tuple key (plugin, tf) for aggregate(); perf_weights reuses `_compute_perf_multipliers` from `setup_performance_updater.py`.
2. Thread `calibration_curves` + `perf_weights` through `run_i7_and_persist` → `aggregate()`
3. Thread through `replay_symbol` signature
4. Load in `_replay_worker` (per symbol) and single-worker path (perf once, calibration per contract)
5. Add `_assert_backfill_integrity(conn, symbols)` — hard sys.exit(1) if was_selected>1 per bar OR duplicate signal_ids. Wire into main after stage 2.
6. Run: `python production/scripts/run_historical_pipeline.py --replay-only --clean --workers 8`. Verify [INTEGRITY PASS].

**Key technical details for implementation:**
- `_load_calibration_curves` SQL: `WHERE symbol = %s OR symbol = '*'` — symbol-specific beats global '*'
- `_load_perf_weights` SQL: `WHERE sample_size >= 100` — then call `_compute_perf_multipliers(stats)`
- Import needed: `from src.intelligence.setup_performance_updater import _compute_perf_multipliers`
- `_assert_backfill_integrity` location: immediately before `run_normalize` (~line 1534)
- Integrity gate call location: after `print(f"\nStage 2 complete: ...")` (~line 2001)
- Test file: `tests/unit/scripts/test_run_historical_pipeline.py`

**How to apply:** Start fresh session, open plan, use subagent-driven-development skill to execute task-by-task.
