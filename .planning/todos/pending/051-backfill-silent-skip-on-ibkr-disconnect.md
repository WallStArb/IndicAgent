# infrastructure_run_historical_pipeline.py silently completes despite mass symbol skip on IBKR disconnect

**Found:** 2026-07-03, during the 22-symbol ETF universe expansion backfill (client-id 41, task bgrd6ohrg).

**What happened:** ~5 hours into a `--fetch-only --symbols <22 symbols> --timeframes 1d,1h,15m,5m` run,
IBKR TWS gateway dropped the socket mid-fetch (`EDV/5m: fetch error — Socket disconnect`, "Peer closed
connection"). The script caught this, reconnected to the **database** ("DB connection stale —
reconnecting before next symbol..."), but never reconnected to **IBKR**. Every subsequent
`qualify_instrument` call for the remaining 16 symbols failed and was skipped with a one-line
"skipped (qualify failed)" log entry. The script then printed "Stage 1 complete: 14,409,690 total
bars stored" and "Backfill complete", and **exited 0**.

Net effect: 6 of 22 requested symbols completed, 16 were silently skipped, and the process reported
success. Nothing in the exit code, log summary, or process status distinguished this from a clean
full run — it required manually diffing the symbol list against `market_data_ohlcv` to discover the
gap.

**Why this matters:** direct violation of the "silent wrong answer is worse than a loud crash"
principle. A multi-hour unattended batch backfill is exactly the scenario where nobody is watching
stdout live — the exit code and summary line are the only signal, and both said success.

**Action:** in `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`:
1. On IBKR disconnect mid-run, attempt IBKR reconnect (not just DB reconnect) before continuing.
2. If `qualify_instrument` fails, treat as fatal for that run (or retry with backoff) rather than
   skip-and-continue silently.
3. Exit non-zero and print a clear "N/M symbols failed" summary if any symbol was skipped.
4. Consider surfacing skipped-symbol count via the D-06 `job_completed_total{job, status}` signal
   (status=partial) so this is visible without reading logs.

**Blocked on:** nothing. Same file/area as [[049-ibkr-error162-heuristic-risk]] (both in
`fetch_historical_bars` / connection-handling territory) — worth fixing together.
