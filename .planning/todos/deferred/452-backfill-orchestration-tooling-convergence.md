---
status: pending
priority: P3
filed: 2026-09-27
source: todo 449 alignment audit (2026-09-27): the campaign wrappers were unversioned and
  the progress tooling had drifted to the retired parallel-lane era
---

# Backfill orchestration tooling convergence after todo 449

## What

The todo 449 chain (started 2026-09-27) wraps the one engineered fetch delegate
(`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`: gap detection,
ON CONFLICT idempotency, (symbol, tf) completion marking, `ohlcv_empty_history` verification)
with retry loops and stall watchdogs under `logs/backfill_ops/` (force-added to git
2026-09-27; `logs/` itself stays ignored). Three generations of that orchestration and its
tooling now overlap:

1. The watchdog/retry skeleton exists three times: `backfill_retry_loop.sh` (the July
   80-symbol campaign original), `intraday_htf_lane.sh`, `intraday_5m_lane.sh`. Deliberate
   adaptation at the time; now copy-paste that will drift.
2. `infrastructure_backfill_progress_check.sh` is keyed to the retired loop (greps
   `backfill_retry_loop.sh`, reads `backfill_watchdog_attempt*.log`): its bar-count deltas
   still work, but its stall detection is blind to the lane watchdog logs
   (`intraday_htf/htf_all_watchdog_*.log`, `intraday_5m/solo_watchdog_*.log`).
3. `infrastructure_client43_progress_sample.sh` self-declares "safe to delete once
   client-43 finishes" (todo 259, done August 2026) and is still on disk.

## Do (in order)

1. Delete `infrastructure_client43_progress_sample.sh` and its CSV.
2. Retire `infrastructure_backfill_progress_check.sh` or re-point it at the lane watchdog
   logs; delete the abandoned parallel-lane graveyard under `logs/backfill_ops/intraday_5m/`
   (`lane0*`, `lane1*`, `lane2*`, `pilot_*`) once its value as evidence for the one-stream
   decision is no longer needed.
3. Factor the shared watchdog/retry skeleton into one sourced lib while editing the lanes
   for the 185-09 stream lease, so the copies cannot diverge further.
4. Decide the wrappers' permanent home (stay force-added under `logs/backfill_ops/` vs a
   move to `scripts/ops/backfill/`); a move is safe only with no lane running.

## Gate

Blocked until the todo 449 chain completes (~mid-October 2026) and phase 185 plan 09's
lease cutover lands (it edits the same lane scripts). Never edit or move a lane script
while its loop runs: bash reads scripts incrementally. Items 1-2 are unblocked earlier if
desired; items 3-4 are not.
