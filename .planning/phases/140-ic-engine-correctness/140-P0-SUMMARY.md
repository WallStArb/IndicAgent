# Phase 140 P0 — IC Engine Correctness: Summary

## What Was Changed and Why

- **Per-scale stride subsampling (`services/ic_engine.py`):** The regime-level
  subsampling block used `stride = max(min_stride, max_lookahead)` = 60 for ALL
  four scales, starving the fast scale (lookahead=1) of 60x observations relative
  to the correct per-scale stride of max(5,1)=5. Fixed by moving subsampling inside
  the scale loop with `scale_stride = max(subsample_min_stride, lookahead_bars)`.
  Degenerate-feature detection was also moved to use `X_regime` (full regime data)
  instead of the stride-60 subsample, ensuring the mask is stable across all scales.

- **ET session-boundary forward returns (`services/forward_return_writer.py`):**
  `complete_{scale}` used only `(open_{scale} IS NOT NULL)`, so a 5m bar at 15:55
  ET was matched to the 09:30 open the next morning across the overnight gap. Fixed
  by adding `fwd_ts_{scale}` LEAD columns and a date-equality check via
  `AT TIME ZONE 'America/New_York'` (DST-aware) for all intraday TFs (5m, 15m, 1h).
  Daily (1d) is unchanged — overnight gaps are part of the daily signal.

- **Dead code removal + freeze-point enforcement:** `all_results_global` accumulated
  all IC rows across symbols but was never consumed (health gauges used per-symbol
  `result["all_results"]` directly). Removed. Both `ic_engine.py` and
  `forward_return_writer.py` now accept `--training-window-end` (ISO 8601, UTC-aware,
  rejects naive datetimes). `corpus_pipeline_run.sh` captures `MAX(bar_ts)` after
  step 1 and passes it explicitly to steps 3 (forward_return_writer) and 4
  (ic_engine), stabilizing PKs across multi-run builds.

## Verification Results

- 18 new unit tests added across two test files, all passing.
- Full `tests/unit/` suite: no new failures (passing).
- `ruff` and `black` clean on both changed service files.
- `--help` on both services shows `--training-window-end` argument.

## Operator Action Required

Before the next corpus run, truncate `forward_returns` and re-run from step 3:

```bash
# Truncate forward_returns (complete_ flags changed for 5m/15m/1h)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -c "TRUNCATE forward_returns;"

# Also truncate feature_ic_scores if training_window_end has shifted
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -c "TRUNCATE feature_ic_scores;"

# Re-run from step 3 (forward_return_writer onward)
bash production/scripts/corpus_pipeline_run.sh --from-step 3
```

The `--training-window-end` argument will now be captured from the corpus and
passed automatically — no manual intervention required for future runs.
