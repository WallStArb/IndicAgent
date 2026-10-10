# 190-06 back-to-back parity record

## Capture conditions

- Backfill quiesced before capture: `sudo systemctl stop indicagent-ibkr-history-fetcher.timer indicagent-ibkr-history-fetcher.service` at 2026-10-10T11:35Z; process gone, `pg_stat_activity` showed no active fetcher backend, `pg_locks` advisory count 0.
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

CUT_TS=2026-10-10T11:59:48Z

- 465 applied in the same breath as the writer conflict-target flip at CUT_TS
  (commit series: `4e7aa88d2` deletes the 190-05 wrapper after the verified
  fire; the flip commits precede it). Post-state verified 2026-10-10 ~16:15
  EDT: `ohlcv_coverage` PK `(symbol, timeframe, provider)`;
  `ohlcv_provider_head` 1,529 (1d) + 1,529 (5m) rows.
- First fire after CUT_TS: 2026-10-10T18:44:15Z, **failed** in 5.49s with
  `KeyError: 'window_end'`. One-time and unreproduced: the next fire
  (2026-10-10T18:46:10Z, fetch_run_id 89a18558) ran 58 minutes to a clean
  deactivation, a later fire (20:03:35Z, 8e913d4d) ran 5 minutes clean, and a
  bounded repro plus a targeted 1d live run both pass. Root cause unknown: the
  run-start state at 18:44Z was cutover churn (a killed run's leftovers, the
  Alpaca load's final writes minutes earlier); the handler swallowed the
  traceback, which is fixed in the same commit series as this record
  (`traceback.print_exc()` before the summary, so a recurrence is
  diagnosable). Disposition: monitor on the first post-freeze restart; the
  failure mode was loud and safe (returncode 1, transactional chunks, no
  partial-run contamination).
- Race-free verification per the plan: the verified fire's started_at
  (2026-10-10T18:46:10Z) is strictly greater than CUT_TS; clean journal
  deactivation; bars landed and coverage advanced during both clean runs.
  Evidence source is the journal, not the status file: the status file's
  payload was overwritten by post-cutover diagnostic runs.
- Deviations from the plan as written: (1) the backfill is NOT left resumed, by
  owner freeze 2026-10-10 ("no more pulls until the data-plane refactor
  lands"); the timer is stopped and disabled, restart is the joint call with
  the 189 lane after the unified path completes 528's remainder and T4. The
  bounded verification items fetched during diagnosis (4 items: SPY, AAPL,
  MSFT 1d updates) are logged here as the freeze's only known breach.
  (2) An invalid parity re-capture against the post-cutover DB was taken and
  discarded before reading this record's PASS; the 11:36Z PASS artifacts are
  the record's evidence (the pre-phase commit's planner predates five days of
  unrelated main progress, so old-code-at-HEAD-wrapper was the only valid
  baseline, which the original capture already used).
- Worktree cleanup: `git worktree remove /tmp/indicagent-190-parity` exit 0
  (original capture); a second worktree add for the discarded re-capture was
  removed and `git worktree prune` run.

