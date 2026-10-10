# 190-06 back-to-back parity record

## Capture conditions

- Drain quiesced before capture: `sudo systemctl stop indicagent-ibkr-history-fetcher.timer indicagent-ibkr-history-fetcher.service` at 2026-10-10T11:35Z; process gone, `pg_stat_activity` showed no active fetcher backend, `pg_locks` advisory count 0.
- Pre-stop state noted: the service was mid-run (PID 579073, started ~08:39Z; previous completed run ended 08:25Z, status partial, 18 item errors during the 190-03..190-05 code-churn window, budget_exhausted true). Stop landed mid-run; per-chunk writes are transactional and resume is from coverage. The mid-run item (NB 1d, pacing/timeout errors visible in the log) is among the error-status rows both dry-runs agree on.
- DB and quarantine state identical between the two captures (minutes apart, nothing wrote in between).

## Commits and timestamps

- OLD fetcher: worktree at pre-phase-190 commit `5ce368c65` (last main commit before the phase's first execution commit `6cdd1d1b0`, the 190-01 RED test), run at 2026-10-10T11:36:41Z via `/home/bg/dev/indicagent/.venv/bin/python scripts/infrastructure/backfill/ibkr_history_fetcher.py --dry-run`.
- NEW fetcher: HEAD `a4cacea20` (190-05 docs commit), run at 2026-10-10T11:36:49Z via `.venv/bin/python scripts/infrastructure/backfill/ohlcv_history_fetcher.py --dry-run`.
- Worktree path: `/tmp/indicagent-190-parity`.

## Verdict: PASS

Both dry-runs planned 3,024 candidate series with identical lane totals (backfill 1d 7, backfill 5m 1,071, gap_fill 5m 196, parity 15m 10, parity 1h 10, update 5m 121, held=current 1,609). All 40 top-ranked data rows are byte-identical after removing the new provider column (field 3 in the new TSV, value `ibkr` on every new-fetcher row, verified on all 40).

Accepted deltas, each verified:

1. **Provider column** on every new-fetcher data row, value `ibkr` (40/40). This is the phase's intended new dimension.
2. **Summary output-path line** differs only in where each run wrote its detailed TSV (worktree `logs/` vs main-checkout `logs/`) and the capture-time suffix in the filename. Not planned-work content.

Not observed (expected to be empty pre-465): floor-driven no-data trip reduction. The floor seeds live in un-applied migration 465, so this delta class is empty by construction, as the plan anticipated. Both runs show identical no-data handling.

Anything else would have been a parity failure; nothing else was found.

## Cleanup

`git worktree remove /tmp/indicagent-190-parity` -> exit 0, `git worktree list` shows no 190-parity entry, `/tmp/indicagent-190-parity` gone.

## Pre-cutover schema state (verified)

- `ohlcv_coverage` PK is still `(symbol, timeframe)` (464 applied: provider column present with default).
- `ohlcv_provider_head` PK still `(symbol, provider)`; 465 un-applied (file present in production/migrations, not in the DB).
- Full unit suite green (`pytest tests/unit/ -q`, exit 0).

## Cutover record (Task 2, appended)

Pending.
CUT_TS=2026-10-10T11:59:48Z
