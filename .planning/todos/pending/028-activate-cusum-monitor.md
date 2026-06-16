# Activate CUSUMMonitor (post-Phase-130)

**Blocked on:** CounterfactualTracker (Phase 130) — needs `counterfactual_pnl_r` populated in `trade_frames`.

## What exists

`src/monitoring/cusum_monitor.py` — fully implemented, never wired in. Page's CUSUM algorithm on per-setup pnl_r series. Writes severity flags (`none`/`warning`/`critical`) to `drift_state` table. `setup_performance_updater` reads these to apply multiplicative penalties to `perf_weights`.

## What needs to change

1. Update `_fetch_outcomes()` — currently queries `signal_ledger.pnl_r` (legacy monolith, dropped in Phase 129). Switch to `trade_frames.counterfactual_pnl_r` joined via `signal_events` for symbol/setup_plugin filter.
2. Wire into a daemon — add `CUSUMMonitor` instantiation and `run_forever()` call to `setup_performance_updater` (or a dedicated `drift_monitor` service).
3. Verify `drift_state` table has `cusum_severity` column and `(symbol, tf)` unique constraint.

## Activation sequence

Phase 129 (data migration) → Phase 130 (CounterfactualTracker populates `counterfactual_pnl_r`) → activate CUSUM.
