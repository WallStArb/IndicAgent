---
status: pending
priority: P3
filed: 2026-09-27
source: todo 449 alignment audit (2026-09-27): the campaign wrappers were unversioned and
  the progress tooling had drifted to the retired parallel-lane era
---

# Backfill orchestration tooling convergence after todo 449

## Done (2026-09-27, owner-approved cleanup)

1. Deleted `infrastructure_client43_progress_sample.sh` and its boundary-test allow-list
   entry (both self-declared temporary; client-43 finished August 2026). Its output CSV
   was already gone.
2. Deleted `infrastructure_backfill_progress_check.sh` and its boundary-test allow-list
   entry: it was keyed to the retired `backfill_retry_loop.sh` loop, so its stall
   detection was blind to the lane watchdog logs. The lane watchdogs
   (`intraday_htf/htf_all_watchdog_*.log`, later `intraday_5m/solo_watchdog_*.log`) are
   the progress/stall monitor now. Recoverable from git history if ever needed.
3. Deleted the abandoned parallel-lane graveyard under `logs/backfill_ops/`
   (`intraday_5m/lane0*`, `lane1*`, `lane2*`, `pilot*`, the aborted morning solo run,
   `intraday_htf/htf0-2_*`, `lane0-2.symbols`): the one-stream decision and its measured
   rates are recorded in todo 449's status. Also pruned rotated service-log archives
   older than 30 days.

Not touched, deliberately: `logs/phase179` (5.2 GB) and `logs/phase181` (2.5 GB) are the
frozen-verdict artifacts `repro_frozen.py` reads; their end-of-life belongs to phase 186
with the sleeve-directory deletion (todo 448), not to this cleanup.

## Remaining (gated)

1. Factor the shared watchdog/retry skeleton (now two copies:
   `intraday_htf_lane.sh`, `intraday_5m_lane.sh`; the original `backfill_retry_loop.sh`
   is kept as the pattern source) into one sourced lib while editing the lanes for the
   185-09 stream lease, so the copies cannot diverge further.
2. Decide the wrappers' permanent home (stay force-added under `logs/backfill_ops/` vs a
   move to `scripts/ops/backfill/`); a move is safe only with no lane running. At that
   point `backfill_retry_loop.sh` can also be deleted (its content lives in git history).

## Gate

Blocked until the todo 449 chain completes (~mid-October 2026) and phase 185 plan 09's
lease cutover lands (it edits the same lane scripts). Never edit or move a lane script
while its loop runs: bash reads scripts incrementally.
