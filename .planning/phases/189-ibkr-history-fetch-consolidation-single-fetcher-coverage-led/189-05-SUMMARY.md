---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 05
subsystem: ibkr-history-backfill
tags: [advisory-lock, manual-tools, ci-guard]
requires:
  - scripts/infrastructure/backfill/_fetcher_lock.py (FetcherLock, FetcherLockHeld, LOCK_HELD_MESSAGE; plan 02)
provides:
  - ops_d1_bootstrap, ops_venue_study, ops_intraday_venue_recovery and the rate-limit probe on the fail-fast FetcherLock
  - IBKR history CI guard accepting FetcherLock (_HOLDS_STREAM_MARKERS)
affects: [189-06, 189-08]
tech-stack:
  added: []
  patterns: [fail-fast lock before provider construction, lock closed in finally]
key-files:
  created: []
  modified:
    - scripts/ops/bars/ops_d1_bootstrap.py
    - scripts/ops/bars/ops_venue_study.py
    - scripts/ops/bars/ops_intraday_venue_recovery.py
    - scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
    - tests/unit/scripts/test_d1_bootstrap.py
    - tests/unit/scripts/test_venue_study_script.py
    - tests/unit/scripts/test_intraday_venue_recovery.py
    - tests/unit/test_ibkr_history_lease_boundary.py
    - .planning/phases/185-daily-data-foundation/deferred-items.md
decisions:
  - "ops_intraday_venue_recovery.py (added by 185-20 after this plan was written) is a manual IBKR history tool, so it moved onto FetcherLock too; on a held lock --apply prints LOCK_HELD_MESSAGE and exits 1, the tool's existing refusal code."
  - "Per-tool refusal exits keep each tool's existing contract: d1 bootstrap 4 (resume hint), venue study 3 (REFUSED via main), venue recovery 1, probe 2."
  - "FetcherLock has no checkpoint(); the lease's per-pair / per-route checkpoints (yield to priority waiters) are deleted, since a fail-fast lock has no waiters to yield to."
metrics:
  duration: ~40 min
  completed: 2026-10-06
  tasks: 2
  files: 9
---

# Phase 189 Plan 05: manual IBKR history tools on the fetcher lock summary

Every manual IBKR history tool (D1 bootstrap fresh-fetch, venue study, intraday venue recovery, chunk and rate-limit probe) now takes the fail-fast `ibkr_history_fetcher` advisory lock before building its IBKRProvider and refuses at once with `LOCK_HELD_MESSAGE` when it is held, instead of queueing on the tiered `ibkr_history_stream` ResourceLease; the CI guard recognises FetcherLock as holding the stream.

## Tasks

| Task | Commit | What |
|------|--------|------|
| 1 | bc7383391 | d1 bootstrap, venue study, intraday venue recovery on FetcherLock; lock-held and granted-path tests; guard accepts FetcherLock |
| 2 | 60e7e4842 | rate-limit probe on FetcherLock (exit 2 on refusal); probe allow-list entry removed; 185 deferred item resolved |

## Behavior

- `ops_d1_bootstrap fresh-fetch`: on a held lock prints `LOCK_HELD_MESSAGE`, then `nothing fetched; rerun with --resume-run <run_id>`, appends a `lock_held` progress event, returns 4. Resume logic is unchanged. The `infra.ibkr_history_lease.%` pattern is gone from `_load_apr`.
- `ops_venue_study`: `hold_or_refuse()`; `FetcherLockHeld` closes the opening connection and propagates to `main()`, which reports `REFUSED: <message>` and exits 3 (status `refused`), where `LeaseTimeout` used to land.
- `ops_intraday_venue_recovery --apply`: refuses with exit 1; `_KEY_LEASE_WAIT` dropped from `_APR_KEYS`.
- Probe: lock acquired right after `Settings()`, before `connect_db` and the provider; the probe body moved into `_probe()` so a `finally` closes the lock; it also now closes its DB connection on a gateway connect failure.
- Holders show in `pg_stat_activity` as `lock:ibkr_history_fetcher:d1-bootstrap:47`, `...:venue-study:48`, `...:intraday-venue-recovery:49`, `...:ibkr-rate-limit-probe`.
- `src/core/resource_lease.py` untouched.

## Deviations from plan

1. **[Rule 2] ops_intraday_venue_recovery.py moved as well.** 185-20 added it after planning; it held the PRIORITY lease and fetches IBKR history. Leaving it would break the plan's goal (no manual tool on the lease). Two tests added in `tests/unit/scripts/test_intraday_venue_recovery.py`.
2. **Guard marker change landed in the Task 1 commit,** not Task 2. Task 1 alone left the three tools without a `ResourceLease` reference, so the guard would have been red at that commit. Task 2 carries the probe and the allow-list removal.
3. **Lease checkpoints deleted.** `lease.checkpoint()` calls in d1 bootstrap (per pair) and venue study (per qualify and per route, with its "yielded lease" print) have no FetcherLock counterpart; the D-22 pair flush is kept.
4. **No separate lock boundary test exists;** the only guard is `tests/unit/test_ibkr_history_lease_boundary.py` (plan 08 renames and rewrites it).
5. **D1/Tradier reconciliation:** the ops tools' fetch paths were unaffected by 185's mutable-D1 (migration 438) and Tradier changes; the Tradier daily loader is not an IBKR fetch caller and needs no lock.
6. **185 deferred item** for the probe marked resolved (`.planning/phases/185-daily-data-foundation/deferred-items.md`).

## Verification

- Targeted: `.venv/bin/pytest tests/unit/scripts/test_d1_bootstrap.py tests/unit/scripts/test_venue_study_script.py tests/unit/scripts/test_intraday_venue_recovery.py tests/unit/scripts/test_fetcher_lock.py tests/unit/test_ibkr_history_lease_boundary.py -q`: 39 passed.
- Probe `--help` runs. ruff, black and all 9 pre-commit checks passed on both commits.
- Full `tests/unit/`: 7976 passed, 5 skipped, 1 failed. The failure, `tests/unit/scripts/test_ops_real_rows_swap.py::test_verify_refuses_before_reading_while_a_writer_runs` (TypeError in the test's fake lambda), comes from another session's uncommitted edit to `scripts/ops/bars/ops_real_rows_swap.py`. In a detached scratch worktree at 60e7e4842 (both my commits, none of that WIP), `test_ops_real_rows_swap.py` passes 29/29.

## Transition window (T-189-19)

From these commits until 189-06 cutover, these tools no longer serialize against the still lease-based todo-449 lanes and nightly. Do not run ops_d1_bootstrap, ops_venue_study, ops_intraday_venue_recovery or the probe until 189-06 completes.

## Notes for 189-06 and 189-08

- After cutover every IBKR history caller except `infrastructure_run_historical_pipeline.py`, the nightly and `ops_head_rerun.py` (which subprocesses the pipeline) is on FetcherLock. Plan 08 retires those and can then drop `ResourceLease` from `_HOLDS_STREAM_MARKERS`.
- APR key `infra.ibkr_history_lease.priority_wait_minutes` now has no reader among the ops tools; check the pipeline and nightly and drop it (and any other `infra.ibkr_history_lease.*` keys) in plan 08's cleanup migration.
- `ops_real_rows_swap.py` already checks both `ibkr_history_stream` and `ibkr_history_fetcher` keys as writer locks, so it covers both regimes.
- Remaining allow-list entries: ibkr.py, base.py, ibkr_adapter.py (permanent), `services/backfill_feature_factory.py` (lease-free, still TEMPORARY) and `_history_fetch_item.py` (run only under the fetcher's lock).

## Known stubs

None.

## Self-Check: PASSED

- FOUND commits: bc7383391, 60e7e4842
- FOUND files: all key-files above
