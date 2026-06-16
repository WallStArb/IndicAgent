# Activate KSDriftMonitor (post-Phase-129)

**Blocked on:** Phase 129 data migration complete; `drift_state` table and signal generator drift hook verified.

## What exists

`src/monitoring/ks_drift_monitor.py` — fully implemented, never wired in. Two-sample KS test on I1/I4 feature distributions from `intelligence_features`. Writes `ks_severity` to `drift_state` table. Signal generator reads via `_refresh_drift_penalties_from_db()` to apply confidence penalties (`DRIFT_PENALTIES`: none=1.0, warning=0.85, critical=0.70). Runs every 4h.

## What needs to change

1. Verify `drift_state` table exists with `(symbol, tf, ks_severity, updated_at)` columns and `(symbol, tf)` unique constraint.
2. Verify signal generator's `_refresh_drift_penalties_from_db()` is still wired and reads `ks_severity` from `drift_state`.
3. Wire `KSDriftMonitor` into a daemon — add instantiation and `run_forever(symbols=get_active_contracts(...))` call to a drift monitor service or `setup_performance_updater`.
4. `intelligence_features` query uses `feature_tf` column — verify column name matches current schema (may be `tf` post-rename).

## Note

`DRIFT_PENALTIES` constant is imported by `src/core/cache_manager.py` — do not delete the file until wired in. The class itself is the dead part; the constant is live.
