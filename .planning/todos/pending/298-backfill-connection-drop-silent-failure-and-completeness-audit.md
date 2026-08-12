# 298 - Backfill connection-drop lacks an automated completeness audit and retry-loop wiring

**Filed:** 2026-08-11
**Corrected:** 2026-08-11, same session -- original filing overstated the gap after only
grep-sampling the log; re-reading the actual code narrowed this considerably. See "What was
wrong with the original filing" below.
**Source:** Follow-up from todo 296 (client-44 connection-drop gaps).
**Status:** pending, not blocking. `max_wal_size` raised 1GB->4GB live via `ALTER SYSTEM` +
`pg_reload_conf()` this session (`pending_restart=false`, confirmed applied) -- the root-cause
half of this todo is done. client-46 re-run covering the known gaps is in flight.

## What was wrong with the original filing

Original text claimed the pipeline "logs nothing at ERROR level" on a connection drop and
called this a silent failure. False -- re-reading
`infrastructure_run_historical_pipeline.py` lines 1306-1308 and 1409-1430 (and confirming
against the actual `logs/backfill_client44_20260810.log`, which has explicit
`"{symbol}/{tf}: fetch error — {e}"` lines for all 6 affected symbols):

- Every fetch exception is caught, printed with the exact symbol+timeframe+error, and counted
  in `fetch_errors`.
- At run end, `fetch_errors > 0` prints `"Backfill FINISHED WITH N FETCH ERROR(S) — not
  declaring complete"`, emits `job_completed_total{job="historical-backfill",
  status="partial"}` (a real OTel metric, not just a print), and `sys.exit(1)`.
- A generic retry wrapper already exists: `logs/backfill_ops/backfill_retry_loop.sh` -- stall
  watchdog (polls real DB bar-count growth, kills+relaunches on no progress), loop-until-
  `"Backfill complete."`-with-no-skips, `MAX_ATTEMPTS=50`. It just wasn't used for the
  client-44/45/46 expansion-cohort runs (hardcoded to `--client-id 40` and no `--symbols` flag,
  written for the original ~80-symbol universe).

So this was never a "silent wrong answer" in the CLAUDE.md sense -- the failure is loud,
correctly propagates a nonzero exit code, and is machine-readable via the OTel metric. The
human-in-the-loop step this session was reading the log by eye, not a missing signal.

## What's actually left

1. **`backfill_retry_loop.sh` doesn't generalize to an arbitrary `--client-id`/`--symbols`
   run.** Any future ad-hoc cohort backfill (like this expansion) either gets manually
   monitored (what happened here) or needs someone to hand-edit the wrapper script. Worth
   parameterizing (`--client-id`, `--symbols` passthrough) so ad-hoc runs get the same
   watchdog+retry-to-completion treatment as the standard universe backfill, instead of a
   human babysitting a raw `nohup` process.
2. **No automated post-run completeness audit distinct from the exit code.** `fetch_errors`
   tells you *a* fetch failed; it doesn't by itself answer "which symbol/tf pairs are still
   short of full depth" without re-grepping. The `n_tf=5`-per-symbol SQL (see
   `project_universe_expansion_and_ibkr_recalibration_2026_08_06` memory) already exists and
   has been run manually multiple times -- wiring it as an automatic end-of-run summary
   (printed + logged, not necessarily alerting anywhere since there's no live consumer of
   backfill status today) would remove the "did it actually finish" ambiguity without adding
   new infra.

Neither is urgent by itself -- (1) is a convenience/consistency gap for future ad-hoc runs,
(2) is a nice-to-have summary that the exit code + manual SQL check already cover today.
Downgrading from P0 accordingly; this isn't a live measurement-integrity gap, it's backfill
tooling polish.

## Where

- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` -- fetch-error
  handling (already correct, see above) and the natural hook point for an end-of-run
  completeness summary
- `logs/backfill_ops/backfill_retry_loop.sh` -- generalize the hardcoded `--client-id 40`
  invocation to accept `--client-id`/`--symbols` passthrough
- Completeness query pattern: `project_universe_expansion_and_ibkr_recalibration_2026_08_06`
  memory
