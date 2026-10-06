---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 04
subsystem: ibkr-history-backfill
tags: [ibkr, fetcher, systemd-watchdog, priority-queue, ohlcv_coverage, dry-run-gate]
requires: [189-01, 189-02, 189-03, 185-18, 185-19, 185-22, 185-23]
provides:
  - "scripts/infrastructure/backfill/ibkr_history_fetcher.py: IbkrHistoryFetcher(BaseBatch), build_parser, validate_args, resolve_scopes, build_candidates, last_session_close, RunPlan, dry_run_rows"
  - "BaseBatch.completion_status (execute() may report partial / lock_held / dry_run)"
  - "services/ohlcv_coverage_writer.refresh_1d_bounds"
  - "_fetch_queue: CoverageRow.last_fetched_at, is_current, PriorityQueue(current_after=...), held_snapshot()"
  - "OHLCV_COVERAGE_SLA_BREACHED_SERIES point gauge"
  - "production/systemd/indicagent-ibkr-history-fetcher.service and .timer (repo only, not installed)"
affects: [189-05, 189-06, 189-07, 189-08]
tech-stack:
  added: []
  patterns:
    - "Type=exec unit with WatchdogSec pinged only from the live event loop, RuntimeMaxSec as the hard bound"
    - "stage subprocesses via asyncio.create_subprocess_exec so watchdog pings continue while they run"
    - "once-per-session-close hold: a settled series is not re-asked until a session has closed since its last fetch"
key-files:
  created:
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py
    - production/systemd/indicagent-ibkr-history-fetcher.service
    - production/systemd/indicagent-ibkr-history-fetcher.timer
  modified:
    - src/core/agent/base_batch.py
    - src/observability/metrics.py
    - services/ohlcv_coverage_writer.py
    - scripts/infrastructure/backfill/_fetch_queue.py
    - tests/unit/test_base_batch_completion_metrics.py
    - tests/unit/scripts/test_fetch_queue.py
    - tests/unit/scripts/test_ohlcv_coverage_atomic_write.py
decisions:
  - "The queue holds a series whose last fetch settled (ok/no_data) at or after the latest NYSE session close. Without it a 15-minute recurring fetcher re-asks every gap-free intraday series each fire during market hours and re-asks every 1d overlap window each fire, spending the one IBKR stream on answers it already has."
  - "1d ledger bounds are recomputed (not widened) from market_data_ohlcv_tradeable by refresh_1d_bounds after a clean daily stage, then fetch_complete is marked (amendment 1)."
  - "Tradier-owned 1d series are skipped by running D2's own probe SQL (services.bar_derivation._SELECT_DAILY_CHANGED_SINCE_SQL, column tradier_owned) per 1d candidate: 931 probes in 0.2 s. Imported, not copied (amendment 2)."
  - "The daily stage runs as --symbols <touched> --apply (the pipeline's form), not --changed-only: split detection's own derive closes a daily batch, which would make --changed-only miss this run's other touched symbols."
  - "The D7 reconciliation audit is handed to a separate daily caller (plan 06/07) instead of running at the end of every 15-minute fire; the fetcher writes the status file the audit reads."
  - "A gateway lost mid-run stops the loop, still runs the non-IBKR run-end stages for what landed, then raises (status failure)."
metrics:
  duration: ~2 h
  completed: 2026-10-06
  tasks: 3
  files: 11
---

# Phase 189 Plan 04: the single IBKR history fetcher summary

`ibkr_history_fetcher.py` is a BaseBatch oneshot that takes the fail-fast FetcherLock,
resolves the default-scope union (4,222 series today, no 1m), works the ledger-ranked queue
one item at a time within an APR budget, records one outcome per item, and then runs the
nightly's run-level stages: split detection, the daily stage with a 1d ledger refresh, and
grid promotion. Its systemd unit runs it as Type=exec with WatchdogSec and RuntimeMaxSec.
The read-only dry run against live state passes every gate check.

## Commits

| Task | Commit | What |
|------|--------|------|
| 1 | 611017b53 | Fetcher, BaseBatch.completion_status, SLA gauge, refresh_1d_bounds, queue current hold, tests for the shared pieces |
| 2 | 7a840594a | 18 fetcher tests, lock_factory seam, systemd service and timer |
| 3 | (no code change) | Dry-run gate executed; results below |

## Verification

- `.venv/bin/pytest tests/unit/scripts/test_ibkr_history_fetcher.py tests/unit/scripts/test_fetch_queue.py tests/unit/scripts/test_fetcher_lock.py tests/unit/scripts/test_history_fetch_item.py tests/unit/scripts/test_ohlcv_coverage_atomic_write.py -q -rs`: all passed, 0 skipped. Both live-lock singleton tests and the live refresh_1d_bounds test ran. The synthetic ZZ189 rows were cleaned up (0 rows left in market_data_ohlcv, ohlcv_coverage, instruments).
- BaseBatch tests (`tests/unit/test_base_batch_completion_metrics.py`, `test_base_batch_jsonb.py`), the coverage-writer, lease, ohlcv and ohlcv-writer boundary tests, the service compliance tests, and `-k service_auditor`: all passed.
- `systemd-analyze verify production/systemd/indicagent-ibkr-history-fetcher.service`: no output, 0 errors.
- `ibkr_history_fetcher.py --help` exits 0 and lists every flag. ruff, black and mypy are clean on the new module. Pre-commit passed on both commits.
- Full `tests/unit/` run: see "Full suite" below.

## Dry-run gate

Run at 2026-10-06 06:23 UTC: `.venv/bin/python scripts/infrastructure/backfill/ibkr_history_fetcher.py --dry-run --dry-run-out logs/ibkr_history_fetcher_dryrun_189-04.tsv` (default scopes). It took 1.4 s.

Read-only evidence:

| Measure | Before | After |
|---------|--------|-------|
| ohlcv_coverage rows, max(last_fetched_at) | 2540, 2026-10-02 15:58:39.576177+00 | 2540, 2026-10-02 15:58:39.576177+00 |
| ohlcv_request rows with caller 'ibkr-history-fetcher' | 0 | 0 |
| ohlcv_request total | 30643 | 30644 |
| `docker logs --since 5m ib-gateway \| grep -c "client 40"` | 0 | 0 |

The one new ohlcv_request row came from the live todo-449 lane. It is `historical-pipeline`, CCBG 1h, from PID 37659, client 46. The dry run never builds the sink, the lock or the provider; the unit test pins this down with recording fakes.

Checks:

- PASS. HPQ 15m is not ranked as zero coverage. Its row has earliest 2006-10-05 13:30, latest 2026-10-01 19:45, gap_days 0, at position 988 in the SLA band.
- PASS. BBY 15m has gap_days 0 (earliest 2006-10-02, position 551).
- PASS. No series is excluded. The excluded count is 0, and consecutive_failures is 0 everywhere.
- PASS. Every sla_breach=True row precedes every sla_breach=False row. The last breaching row is at position 1536 and the first non-breaching row is at 1537.
- PASS. Within the non-breaching band, every tf_class -1 row precedes every tf_class 0 row. That band holds 1,943 tf_class -1 rows and 0 tf_class 0 rows: every queued 5m and 1d series breaches the SLA, see finding 2.
- PASS. No 1m row appears in the TSV.
- PASS. The total pair count matches the default-scope union. The TSV has 4,222 rows and 4,222 unique pairs. That is compute 233 x {1d, 1h, 15m, 5m} = 932, plus 698 compute_1d-only 1d, plus 1,529 backfill x {1h, 15m} minus the 466 compute overlap = 2,592. 743 of those are Tradier-owned 1d series, held with reason tradier_owned, which leaves 3,479 queued.
- Known pre-existing failure, not counted against the fetcher: todo 490, where the grid stage's archive verify fails on twice-observed revised bars (7 symbols) and the stage exits nonzero. It belongs to the 185 session. Until it is fixed, every fetcher run that lands 5m rows ends `partial` (finding 5).

Queue shape: 15m 1,529, 1h 1,529, 5m 233, 1d 188. The SLA band holds 1,536 series: 1,115 at 15m/1h, then 421 at 5m/1d. 1,943 queued 15m/1h series have no ledger row.

Top 40, new order against legacy:

| # | New (fetcher) | Legacy (a) backfill `_reorder_contracts_by_gap`, 1h/15m | Legacy (b) nightly compute leg `_select_stalest` |
|---|---------------|------------------------------------|-----------------------------------|
| 1-9 | IP/15m, ECH/15m, ECH/1h, HCKT/15m, HCKT/1h, ECHO/15m, ECHO/1h, FRST/15m, FRST/1h | AAON, ABCB, ADC, AEIS, AFG, AIT, ALKS, ALNY, AMG | MMM, MO, MRK, MS, MSFT, MSTR, NAD, NEM, NFLX |
| 10-40 | MMM, MO, MRK, MS, MSFT, MSTR, NAD, NEM, NFLX, NLY, NUE, NVDA, NVR, OXY, PFE, PG (each 15m then 1h) | AMKR, AN, ANF, ARW, ATI, ATR, AUB, AVT, AXS, AYI, BC, BIO, BKH, BLDR, BMRN, BPOP, BRKR, BWA, CBSH, CBT, CCI, CCK, CCL, CCO, CDE, CDNS, CE, CENT, CF, CFFN, CGNX | NLY, NUE, NVDA, NVR, OXY, PFE, PG, PGR, QCOM, QQQ, R, REGN, RSP, RTX, SHW, SLB, SLV, SO, SPG, SPY, T, THC, TIP, TLT, TOL, TRV, TSLA, TSM, UBER, UNH, UNP |

What drives each difference:

- Legacy (b) matches the new order. Its top 40 (MMM through UNP) appear at new positions 10 through 87 in the same relative order. Both rank on staleness (7 days here). The new queue interleaves 15m and 1h because it ranks series, not symbols.
- New positions 1-9 lead because of the coverage-gap element inside the SLA band. IP 15m starts in 2012 while IP's proven depth reaches 2006, a 2,185-day gap. ECH and HCKT have 42- and 29-day gaps. Legacy (b) ranks on the latest 1h bar alone and cannot see an early-history gap.
- Legacy (a)'s top 40 sit at new positions 1,541 and later (except CCI 647, CCL 649, CDNS 651, CENT 659, CF 661, CFFN 663, which have ledger rows). They are backfill-dimension names with no 1h/15m ledger row. The new rank (plan 02, interpretation 1) puts never-fetched series after the SLA band, so freshness of the 1,536 covered series comes before the HTF campaign's untouched names. Legacy (a) has no freshness term and puts the largest-gap names first. This is the intended CD-06 behavior.

Findings that plans 06 and 07 must act on:

1. The ledger has been frozen since 2026-10-02 15:58 UTC. The live lane writes through `persist_chunk_atomically(coverage=None)`, so its work never reaches ohlcv_coverage. Since the freeze the lane has answered 15m for 375 series (330 with no ledger row) and 1h for 376 (330 with no ledger row), and 1d requests touched 1,529 series. Correctness is unaffected, because item planning reads the request and bar record rather than the ledger. Ranking is stale for about 750 series, though. The current hold holds nothing today because no last_fetched_at is after the latest close. **Plan 06 must refresh ohlcv_coverage from stored state after the lane stops and before the fetcher's first real run.** Migration 432's bootstrap is ON CONFLICT DO NOTHING, so it will not update existing rows. The refresh needs a DO UPDATE form added to `services/ohlcv_coverage_writer.py`, the single writer. Running it now would be stale again within minutes while the lane runs.
2. Every series with a ledger row breaches the 3-day SLA. That follows from finding 1, and from the 1d bounds never having moved since bootstrap (fixed going forward by `refresh_1d_bounds`). After a refresh, the band should hold only genuinely stale names. Staleness is measured in calendar days, so the Tuesday after a 3-day weekend puts the whole universe in the band, which degenerates to plain staleness order. That is harmless and was left as is.
3. 743 of the 931 1d series are Tradier-owned and skipped, so the fetcher queues only 188 1d series. The nightly still dispatches all 698 compute_1d-only names to IBKR at 1d until 185-26 lands.
4. The split-detection re-fetch (`ops_split_detect.refetch_command`) launches `infrastructure_run_historical_pipeline.py`. Today that takes the ibkr_history_stream lease, not FetcherLock, so it works while the fetcher holds its lock (the fetcher disconnects its own client first and passes its own `--client-id`). **Once plan 08 moves the pipeline under FetcherLock, that re-fetch will be refused by the fetcher's own lock.** Plan 07/08 must rewire it, for example as a re-fetch done in-process by the fetcher, or a FetcherLock-exempt child.
5. Todo 490 makes the grid stage exit nonzero, so fetcher runs that land 5m rows end `partial` until it is fixed.

## Nightly legs carried over, handed off, or dropped

From the nightly as it stands after 185-23 (re-read at execution):

| Nightly step | Fetcher |
|--------------|---------|
| compute leg and compute_1d-only leg (IBKR fetch) | Replaced by the default-scope queue |
| `--overlap-sessions` from APR `infra.bar_derivation.overlap_sessions` | `FetchContext.overlap_sessions`, read at startup. Because of the current hold, a 1d series is asked at most once per session close, like the nightly |
| `ops_split_detect.py --fetch-run-id` (185-22) | Ported as a run-end stage when any 1d item delivered bars |
| daily stage | Ported as `--symbols <touched> --apply`, then `refresh_1d_bounds` and `mark_fetch_complete` |
| grid stage | Ported as `--changed-only --apply` when n_grid_source_rows > 0, with no exclude file under the lock |
| lane-guard exclude file | Dropped: no other IBKR writer can exist under FetcherLock |
| lease-timeout integrity fact | Dropped: there is no lease. A held lock is `lock_held`, exit 0 |
| `logs/nightly_backfill_status.json` (185-23) | Written by the fetcher at the end of every locked run, with the same keys plus `job` and `started_at`. Status success/partial/failed; not written for lock_held or dry runs. It is not written as 'started' at entry, because during a 4-hour run the audit would read that as a finding. A run killed before finishing leaves the previous status, which ages into the audit's 26-hour stale check |
| `services/bar_reconciliation_audit.py` last step | **Handed to a separate daily caller.** A per-fire audit every 15 minutes would be wasteful, and an independent timer also catches a fetcher that never runs. Plan 06/07 must add a timer for `indicagent-bar-reconciliation-audit.service`, which has no timer today, before deleting the nightly |
| Tradier daily load (185-26, not landed) | Stays `infrastructure_run_tradier_daily.py` with its own caller. Only the Tradier-owned predicate is shared |

Readers of `logs/nightly_backfill_status.json`:
- `services/bar_reconciliation_audit.py`: `NIGHTLY_STATUS_FILE`, read by `_nightly_skipped` and judged by `check_nightly_skipped` (anything but a `success` with `finished_at` within `threshold.bar_reconciliation.nightly_max_age_hours` (26) is a finding).
- `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`, the current writer, which plan 07 deletes.
- `tests/unit/scripts/conftest.py`, which redirects the nightly's `_STATUS_FILE` in tests.

No Grafana dashboard, script or doc outside `.planning` reads it. Once the fetcher is the writer, `partial` is a finding to the audit, as the nightly's `failed` was.

## Deviations from plan

### Reconciled with what shipped (amendments and 189-01..03)

1. **[Rule 2] Current hold in the queue** (`_fetch_queue.is_current`, `PriorityQueue(current_after=)`, `CoverageRow.last_fetched_at`, `held_snapshot`). The plan's loop plus a 15-minute timer would re-ask every gap-free series on every fire: intraday slots all day, and every 1d overlap window every fire. That is about 2,500 requests per fire against a 58-requests-per-10-minutes limiter, and it would starve 5m and 1d behind 15m/1h tails. The rule is parameter-free and uses the NYSE calendar; all 1,529 active instruments are equity. Tests were added to `test_fetch_queue.py`. Commit 611017b53.
2. **Tradier skip through D2's probe.** The predicate is an inline EXISTS inside `_SELECT_DAILY_CHANGED_SINCE_SQL`, not an importable predicate. To import rather than copy it without editing `bar_derivation.py` (185-owned, and executed by the live lane's daily stage), the fetcher runs the whole probe per 1d candidate and reads `tradier_owned`. That takes 0.2 s for 931 symbols. A shared public predicate would be cleaner, which is a 185/189-08 follow-up.
3. **Daily stage form:** `--symbols <touched> --apply`, not the nightly's `--changed-only`, for the reason given in the decisions above. As a result, a corporate action recorded by another writer for a symbol the fetcher did not touch is not re-derived by the fetcher. Split detection derives its own symbols. The nightly has the same `--changed-only` blind spot whenever split detection derives first, and that belongs to the 185 session.
4. **D7 audit and status file:** handed to a separate caller, as tabulated above.
5. **`--real-bars-only` dropped from the CLI.** 185-18 retired the flag (189-03 deviation 4), and `real_bars_only_for(tf)` is fixed per timeframe.
6. **Scope semantics:** with no `--dimension` and no `--timeframes`, the run is the default-scope union, and `--symbols` narrows it. `--timeframes` alone applies to `compute`. `--dimension` alone uses that dimension's default_scopes entry, so 1m is dropped (todo 455), not the pipeline's `1d,1h,15m,5m,1m` default.
7. **Watchdog ping cadence while awaiting a stage:** `history_request_timeout / 3` (300 s at the seed), the same cadence as the in-item `on_tick`, instead of a literal 30 s. One WatchdogSec bound then covers both, and no new literal is introduced.
8. **BaseBatch tests** extend the existing `tests/unit/test_base_batch_completion_metrics.py`. No BaseBatch test lives under `tests/unit/core/`.
9. **Extra seams:** `lock_factory`, `context_factory`, `connect`, `contracts_for` and `status_file`, so non-singleton tests run without a database. Each replaces exactly one dependency.

### Not done here, by hard rule

- **`services/service_auditor.py` registry entries** (`_DAG_ORDER` priority 8 and the inactive-is-correct oneshot set). The orchestrator's hard rules list this file as another session's and forbid touching it. Plan 06, which installs the unit, must add both lines: `"indicagent-ibkr-history-fetcher": 8` beside bar-derivation, and the inactive-is-correct entry. The acceptance grep for 2 lines is not met in this plan. The `-k service_auditor` tests pass without the entries.

### TDD gate compliance

Task 2 is marked tdd. Its tests were written after task 1 had built the implementation (the plan orders task 1 first), so they passed on first run and no separate RED commit exists. The behaviors were checked by the assertions themselves. The dry-run test, for example, fails if any statement other than a SELECT is issued.

## Full suite

`.venv/bin/pytest tests/unit/ -q` exited 0 with no failures. Its 5 skips are all pre-existing and unrelated: the pipeline annotation test, a determinism sleeve config, two cost-hurdle imports and a degenerate HMM. The writer-boundary failure on the Tradier loader no longer appears, because 305268e9c is in the tree.

The dry-run TSV is at `logs/ibkr_history_fetcher_dryrun_189-04.tsv`, on disk only (`logs/` is git-ignored). This section carries the evidence.

## Known stubs

None.

## Threat flags

None beyond the plan's register. `--reset-failures` writes only through `reset_failures` under SET LOCAL ROLE bar_derivation_writer (T-189-15). The new `refresh_1d_bounds` sits in the single writer module, covered by the boundary test.

## What 189-05 and 189-06 must know

- Before the first real run: stop the lane, refresh ohlcv_coverage from stored state (finding 1), add the service_auditor entries, add an audit timer, then install and enable the timer. A one-shot `--budget-minutes` manual run first is cheap insurance.
- `--client-id` defaults to 40. The lane uses 46 and the nightly 45. Split detection uses the fetcher's own `--client-id` after the fetcher disconnects.
- The unit's WatchdogSec=1200 holds while the ping gap, `infra.ibkr.history_request_timeout / 3` (300 s at the 900 s seed), stays well below 1200 s. Raising that APR key past about 2,400 s needs a matching WatchdogSec change. Keep RuntimeMaxSec (18000) above `infra.backfill.run_budget_minutes` plus about 60 min for stages.
- Exit 0 covers success, partial, lock_held and dry_run. Exit 1 means gateway unreachable or lost, or an unexpected error.

## Self-Check: PASSED

- FOUND: scripts/infrastructure/backfill/ibkr_history_fetcher.py, tests/unit/scripts/test_ibkr_history_fetcher.py, production/systemd/indicagent-ibkr-history-fetcher.service, production/systemd/indicagent-ibkr-history-fetcher.timer, logs/ibkr_history_fetcher_dryrun_189-04.tsv
- FOUND commits: 611017b53, 7a840594a
