---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 06
status: partial
subsystem: ibkr-history-backfill
tags: [cutover, systemd, ohlcv_coverage, tradier, d7-audit]
requires: [189-04, 189-05, 185-26]
provides:
  - "services/ohlcv_coverage_writer.rebuild_from_stored_state and the fetcher's --rebuild-coverage flag"
  - "indicagent-tradier-daily.service/.timer (01:30 UTC): the nightly's Tradier leg on its own caller"
  - "indicagent-bar-reconciliation-audit.timer (06:00 UTC): the D7 audit on its own caller"
  - "service_auditor registry entries for indicagent-ibkr-history-fetcher and indicagent-tradier-daily"
affects: [189-07, 189-08]
key-files:
  created:
    - production/systemd/indicagent-tradier-daily.service
    - production/systemd/indicagent-tradier-daily.timer
    - production/systemd/indicagent-bar-reconciliation-audit.timer
    - .planning/phases/189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led/deferred-items.md
  modified:
    - services/ohlcv_coverage_writer.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - services/service_auditor.py
    - tests/unit/scripts/test_ohlcv_coverage_atomic_write.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py
    - tests/unit/scripts/test_tradier_daily_plan.py
decisions:
  - "The ledger rebuild is migration 432's bootstrap aggregate as DO UPDATE, run by the fetcher under FetcherLock (--rebuild-coverage) so no chunk delta can interleave; consecutive_failures is never touched, and last fetch advances only when a newer SMART TRADES request exists"
  - "The Tradier loader reads infra.tradier.nightly_enabled itself under --nightly (the nightly read it; a direct unit caller would bypass the switch) and emits job_completed_total{job=tradier-daily}; exit 4 (refusals) is SuccessExitStatus"
  - "The smoke run ran as a transient systemd unit with the installed unit's Type/Watchdog/NotifyAccess/RuntimeMax properties, so the watchdog ping path was proven under systemd, not with a no-op notifier"
metrics:
  completed: 2026-10-06 (partial; paused by the owner at 13:03 UTC)
  tasks: "3 of 3 executed; task 3's wait for the first timer-fired run to finish was not completed"
---

# Phase 189 Plan 06: cutover to the single IBKR history fetcher summary (PARTIAL)

**PARTIAL: the owner paused the cutover at 13:03 UTC.** Everything up to and including timer
enable is done and verified. The one open step is to watch the first timer-fired fetcher run
finish and record its outcome (task 3, steps 5 and 6). That run was in flight at the pause,
under systemd and its watchdog, and was left running: stopping it would have been a new live
step. The old lane is stopped, the nightly timer is disabled, and the fetcher, Tradier and D7
audit timers are enabled. They were enabled only after the bounded live smoke run passed
every check.

## Live state at the pause (2026-10-06 13:03:26 UTC)

| Component | State |
|-----------|-------|
| todo 449 chain/lane/pipeline (`intraday_chain.sh`, `intraday_htf_lane.sh`, `infrastructure_run_historical_pipeline.py`) | stopped, 0 processes |
| `lease:ibkr_history_stream:%` backends | 0 |
| `indicagent-nightly-backfill.timer` / `.service` | disabled, inactive (unit files kept; plan 07 deletes them) |
| `indicagent-ibkr-history-fetcher.timer` | enabled, active (OnUnitInactiveSec=15min) |
| `indicagent-ibkr-history-fetcher.service` | active: PID 539753, timer-fired at 12:52:27 UTC, default scopes, client 40; WatchdogUSec=20min, last ping 13:03:24 UTC |
| `lock:ibkr_history_fetcher:ibkr-history-fetcher:40` | held by that run (by design; a session lock, released at exit) |
| `indicagent-tradier-daily.timer` | enabled, active, next 2026-10-07 01:30 UTC |
| `indicagent-bar-reconciliation-audit.timer` | enabled, active, next 2026-10-07 06:00 UTC |
| first-run progress at the pause | 5 items ok (15m x3, 1h x2), 0 errors |

## Remaining steps, in order

1. Wait for PID 539753 to exit. `systemctl is-active indicagent-ibkr-history-fetcher.service`
   should leave `active`. Worst case is about 240 min of budget plus run-end stages. The
   RuntimeMaxSec=5h bound and the watchdog kill a hung run.
2. Confirm `Result=success` and a `run summary:` line with status success or partial in
   `journalctl -u indicagent-ibkr-history-fetcher.service`. Expect partial if 5m rows landed,
   because todo 490 fails the grid stage for A, AAP, ABBV, ACRS, ACVA, ADBE and ADP. Also
   confirm there is no "Watchdog timeout" line.
3. `systemctl list-timers | grep ibkr-history-fetcher` should show the next fire about 15 min
   after the exit.
4. Record the first run's counts, status and `sla_breached` value in this summary, then drop
   the PARTIAL marker.
5. Watch the first timer-fired `indicagent-tradier-daily` run at 2026-10-07 01:30 UTC. The run
   verified here (12:36 UTC) used the loader as it stood before 185-27 landed (32842eaac,
   lineage, scrub and digests). The 01:30 fire is the first unit run of that code.

Not to do: restart the old lane, or re-enable the nightly as a workaround.

## Task 1: gate, stop and disable the old actors

- Gate: 189-04's dry-run gate lists every check PASS. `pytest tests/unit/scripts` plus the
  lease, ohlcv-writer, ohlcv and coverage-writer boundary tests passed on main (2
  pre-existing skips).
- Timing: started 12:29 UTC, well clear of the 23:59 gateway restart and the 05:00 nightly
  slot. The gateway had been up 10 h, its log showed no 2FA prompt, and the live probe
  (below) succeeded.
- Before (12:29:51 UTC):
  - `304460 bash logs/backfill_ops/intraday_chain.sh`
  - `304462 intraday_htf_lane.sh htf_all 46 .../all.symbols` (child of 304460)
  - `304567 infrastructure_run_historical_pipeline.py --dimension backfill --timeframes 1h,15m --client-id 46 --symbols <all>` (child of 304462)
  - `304568` lane watchdog subshell, with `510868 sleep 300`
  - backend `517787 lease:ibkr_history_stream:bulk:historical-pipeline:46` (idle)
  - `indicagent-nightly-backfill.timer`: enabled, inactive, last fired 2026-10-02
- Stop at 12:33:58 UTC, top down by verified PID: chain 304460 first, so it could not launch
  the 5m lane, then lane loop 304462, then watchdog 304568 and its sleep 510868, then the
  python child 304567. Ten seconds later 0 matching processes remained. The lease backend
  closed with its process, no termination was needed, and `pg_locks` held no advisory locks.
  The lane was mid-item on CTAS/15m. The bars it had stored are committed (atomic chunks), and
  the request log lets the fetcher's gap planner resume the rest.
- `systemctl disable --now indicagent-nightly-backfill.timer`, `stop` and `reset-failed` the
  service. Both now read disabled and inactive.

## Ledger rebuild (hard rule 6, 189-04 finding 1)

Commit a3ea7875d adds `rebuild_from_stored_state` in `services/ohlcv_coverage_writer.py`, the
only ledger writer. It is migration 432's bootstrap aggregate with `ON CONFLICT DO UPDATE`:

- earliest, latest and row_count are recomputed from `market_data_ohlcv_tradeable`, plus the
  raw archive for 15m/1h;
- missing series are inserted;
- the latest SMART TRADES request advances last_fetched_at and status only when it is newer;
- consecutive_failures is never touched.

The fetcher's `--rebuild-coverage` flag runs it under FetcherLock. Tests: a live
synthetic-symbol case (stale row recomputed in place, failure counter kept, the scoped
rebuild touches nothing else) and a lock-path case (no IBKR; lock_held refuses).

A preview in a rolled-back transaction came first, then the real run at 12:35:12 UTC: 3796
rows written, about 28 s, lock released.

| | Before | After |
|---|---|---|
| rows | 2540 | 3796 |
| sum(row_count) | 167,263,734 | 212,144,874 |
| max(last_fetched_at) | 2026-10-02 15:58:39 | 2026-10-06 12:33:27 (the lane's last request) |
| rows with consecutive_failures > 0 | 0 | 0 |
| 15m rows / sum / max latest | 557 / 60,444,555 / 2026-10-01 19:45 | 887 / 93,350,614 / 2026-10-05 19:45 |
| 1h | 558 / 16,594,777 / 2026-10-01 19:00 | 888 / 25,458,558 / 2026-10-05 19:00 |
| 1d | 931 / 3,863,639 / 2026-10-01 | 1527 / 6,974,939 / 2026-10-02 |
| 1m, 4h, 5m | 233, 2, 259 rows | unchanged (no writer since the bootstrap) |

Why the counts are right: 15m and 1h each gain exactly 330 series, the number 189-04
measured as answered by the lane with no ledger row. The 1d rows grow because Tradier's
loads gave 1d bars to names the bootstrap never saw. No row has inverted bounds or a
negative count.

## Own callers for Tradier and the D7 audit (amendments 1 and 3)

Commit 3db5ac6ef:

- `indicagent-tradier-daily.service` runs `infrastructure_run_tradier_daily.py --nightly` as
  a oneshot with `SuccessExitStatus=4`, `TimeoutStartSec=1h`, and
  `Before=indicagent-ibkr-history-fetcher.service`. Its timer fires daily at 01:30 UTC.
- The loader now checks `infra.tradier.nightly_enabled` under `--nightly` and emits
  `job_completed_total{job="tradier-daily"}`. Exit 0 is success, 4 is partial, anything else
  is failure.
- `indicagent-bar-reconciliation-audit.timer` fires daily at 06:00 UTC. The audit service had
  never been installed on the host; the repo copy is installed unchanged.
- `service_auditor.py` was clean (no other session's edits), so `_DAG_ORDER` priority 8 and
  `_ONESHOT_UNITS` entries were added for the fetcher and the Tradier unit. There is no
  `_AGENT_ID_TO_UNIT` entry, because neither consumes Kafka.

First run of each:

- Tradier: `systemctl start indicagent-tradier-daily.service` from 12:36:06 to 12:43:38 UTC,
  Result=success. Output `{'loaded': 1266, 'short_history': 27}` (exit 4, the expected 27
  short-history names). 1,265 names gained the 2026-10-05 session, and ETHA's
  `tradier_refetch` split row (effective 2026-10-02) is present. `systemctl show` reports
  ExecMainStatus=0 for any inactive oneshot, including a probe that exits 4, so Result is
  the signal to read.
- D7 audit: Result=success in 54 s. `tradier_refused` 0 of 1266 judged. `nightly_skipped` 1
  finding: the status file read `partial` from the smoke run (todo 490, see deferred items).

## Task 2: bounded live smoke run

- Gateway probe on client 41: SPY 1h for 2 days returned 14 bars, the last at 2026-10-05
  15:00 EDT.
- Queue check (dry run, `--symbols SPY,DIA,CTAS`): SPY, which Tradier owns, was queued at
  15m, 1h and 5m and held `tradier_owned` at 1d. DIA, which it does not own, was queued at
  1d. CTAS was held `current` because the lane answered it after the last close.
- Run: a transient unit `indicagent-ibkr-history-fetcher-smoke` with the installed unit's
  Type=exec, WatchdogSec=1200, NotifyAccess=main and RuntimeMaxSec=18000, running
  `--symbols SPY,DIA --budget-minutes 10 --client-id 42`. Baselines at T0 = 12:45:12 UTC:
  ohlcv_request 32477, max(last_fetched_at) 12:33:27.
- Singleton: once `lock:ibkr_history_fetcher:ibkr-history-fetcher:42` appeared, a second
  invocation on client 43 exited 0 in 1 s with "ibkr history fetcher lock held by another
  process; exiting" (`logs/ibkr_history_fetcher_singleton_189-06.out`).
- Watchdog: WatchdogUSec=20min was in effect, and WatchdogTimestamp advanced 12:45:18 ->
  12:45:29 with no timeout. The 5-minute grid stage stayed under the 300 s stage-ping cadence.
- Run summary (fetch_run_id 4e5bf9ba-6259-4335-b51c-fdf9f02b5004), status partial, unit
  Result=success, 5 min 44 s:
  `{"n_items": 7, "n_ok": 7, "n_no_data": 0, "n_error": 0, "n_bars": 1405, "n_grid_source_rows": 1014, "n_1d_derived": 1, "budget_exhausted": false, "gateway_lost": null, "sla_breached": 0, "stages": {"split_detect": 0, "daily": 0, "grid": 1}}`.
  The grid failures are exactly todo 490's seven symbols. The status file was written
  `partial`, returncode 0. Journal: `logs/ibkr_history_fetcher_smoke_189-06.out`.
- Effects:
  - ohlcv_request 32477 -> 32484, one `bars` request per item under the fetch_run_id, caller
    ibkr-history-fetcher.
  - 7 coverage rows have last_fetched_at after T0, all ok with 0 failures.
  - No SPY 1d IBKR request since T0.
  - No lock or lease holder remained afterwards, and pg_locks held no advisory locks.
- Spot check:
  - SPY and DIA 15m: ledger latest_timestamp equals archive max (2026-10-05 19:45), and
    row_count equals a from-scratch recompute.
  - DIA 1d was refreshed by refresh_1d_bounds and matches a recompute.
  - 1h trails a recompute by 30 min (deferred item 4: the bootstrap's union counts a
    derived grid 19:30 bar).
  - SPY 1d trails because owned 1d rows are never refreshed (deferred item 5).
- `job_completed_total`: emitted, but it never reaches Prometheus. The collector's
  Prometheus exporter drops every metric with a `job` label (`duplicate label names in
  constant and variable labels`). This affects every job since 2026-06-22 (deferred item 1).
  The fetcher's own `ohlcv_coverage_sla_breached_series` shows in the same collector errors,
  which proves its metrics reach the collector.

## Task 3: install and enable

- Installed at 12:35 UTC into `/etc/systemd/system/`: the fetcher service and timer, the
  Tradier service and timer, the audit timer, and the audit service (12:36).
  `systemd-analyze verify` reported no errors on any of them.
- Timers enabled at 12:52:27 UTC, after the smoke run passed. The fetcher timer fired at once
  because OnBootSec had long elapsed, so the first run is timer-fired; the manual
  `start --no-block` was a no-op.
- `systemctl show`: Type=exec, NotifyAccess=main, RuntimeMaxUSec=5h, WatchdogUSec=20min (in
  effect once running). `list-timers --all` no longer lists the nightly.
- Not done: the first run's end, its next-fire time and summary values (remaining steps 1-4).

## Commits

| Commit | What |
|--------|------|
| a3ea7875d | rebuild_from_stored_state, `--rebuild-coverage`, tests |
| 3db5ac6ef | Tradier and audit callers, loader gate and metric, registry entries, tests |
| (this commit) | deferred-items.md and this partial summary |

## Verification

- `pytest tests/unit/ -q` exited 0, excluding `test_ops_real_rows_swap.py`, which 189-05 left
  out because of another session's WIP. Skips are the same pre-existing 5.
- Targeted runs passed: the coverage atomic-write (live), fetcher, coverage-writer boundary,
  Tradier plan, nightly Tradier leg, writer boundary and `-k service_auditor` tests. Synthetic
  ZZ189 rows were cleaned up (0 left).
- ruff and black are clean on touched files. Pre-commit 9/9 passed on both commits. mypy shows
  one pre-existing `no-any-return` in `reset_failures`.

## Deviations from plan

1. [Hard rule 6, Rule 2] The ledger rebuild is new code. The plan said "code is not changed",
   but 189-04 finding 1 and the cutover rules require a refresh before the first real run.
2. [Amendments 1 and 3, Rule 2] New Tradier and audit units and timers. The loader gained the
   APR gate it used to inherit from the nightly, and a D-06 metric. Without them the unit
   caller would ignore the operator switch and stay invisible.
3. [Hard rule 7] The smoke run was narrowed to `--symbols SPY,DIA` with a 10-minute budget,
   not the plan's default scopes at 20 minutes. It ran as a transient systemd unit so the
   watchdog path was exercised. The concurrent invocation used client 43, not the default 40.
4. The audit service unit was not installed on the host, so it was installed from the repo,
   unchanged.
5. `service_auditor.py` also gained an `indicagent-tradier-daily` entry (a new oneshot unit),
   beyond the fetcher entries rule 9 named.
6. Owner pause at 13:03 UTC: the first timer-fired run was left running under systemd and its
   outcome is not recorded.

## Known stubs

None.

## Threat flags

None beyond the plan's register. Sudo use was limited to systemctl, unit copies and two
throwaway `systemd-run` exit-status probes; the credential appears nowhere in logs, commits
or this file.

## Self-Check: PASSED

- FOUND: services/ohlcv_coverage_writer.py (rebuild_from_stored_state),
  production/systemd/indicagent-tradier-daily.service, .timer,
  production/systemd/indicagent-bar-reconciliation-audit.timer, deferred-items.md,
  logs/ibkr_history_fetcher_smoke_189-06.out, logs/ibkr_history_fetcher_singleton_189-06.out
- FOUND commits: a3ea7875d, 3db5ac6ef
