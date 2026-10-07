---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 07
subsystem: ibkr-history-backfill
tags: [deletion, apr, migration-445, systemd, CD-10, CD-11, data-layer-integrity]
requires: [189-06, 185-44]
provides:
  - "migration 445: infra.backfill.default_scopes = {\"compute_1d\": [\"1d\", \"5m\"]}, priority_tf_order = [\"5m\"] (vendor 15m/1h no longer queued)"
  - "the nightly backfill, its units (repo and host), the grid lane guard, the todo 449 lane scripts, chain, retry loop and tracked symbol lists are gone"
affects: [189-08, 189-09, 189-10, 185-28, 185-31, 185-36, 185-38]
tech-stack:
  added: []
  patterns: ["code and the tests that exercise it retire in one commit; tests of surviving code move, not die"]
key-files:
  created:
    - production/migrations/445_backfill_scopes_stop_vendor_htf.sql
    - tests/unit/test_backfill_scopes_migration_contract.py
  modified:
    - services/bar_derivation.py
    - services/service_auditor.py
    - services/bar_reconciliation_audit.py
    - production/systemd/indicagent-bar-derivation.service
    - production/systemd/indicagent-bar-reconciliation-audit.service
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - scripts/ops/bars/ops_real_rows_swap.py
    - src/providers/ibkr.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/scripts/test_ops_real_rows_swap.py
    - tests/unit/scripts/test_tradier_daily_plan.py
    - docs/operations/operations-database.md
    - docs/reference/gotchas.md
    - docs/reference/services/overview.md
  deleted:
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
    - production/systemd/indicagent-nightly-backfill.service
    - production/systemd/indicagent-nightly-backfill.timer
    - scripts/ops/bars/ops_grid_lane_guard.py
    - tests/unit/scripts/test_infrastructure_nightly_backfill.py
    - tests/unit/scripts/test_nightly_lease.py
    - tests/unit/scripts/test_grid_lane_guard.py
    - tests/unit/scripts/test_nightly_tradier_leg.py
    - tests/unit/scripts/conftest.py
    - logs/backfill_ops/intraday_htf_lane.sh
    - logs/backfill_ops/intraday_5m_lane.sh
    - logs/backfill_ops/intraday_chain.sh
    - logs/backfill_ops/backfill_retry_loop.sh
    - logs/backfill_ops/intraday_htf/all.symbols
    - logs/backfill_ops/intraday_htf/quarantined.symbols
    - logs/backfill_ops/intraday_5m/solo.symbols
decisions:
  - "Migration 445 changes config_state only (value, version, config_history); the config_schema seed and description are untouched and logged as deferred item 6"
  - "Three tests in the nightly's Tradier-leg file tested surviving code (the loader's ownership predicate vs D2, the D7 tradier_refused check); they moved to test_tradier_daily_plan.py instead of being deleted"
  - "ops_real_rows_swap's writer-process and writer-unit lists drop the deleted names and gain ibkr_history_fetcher.py and the fetcher and Tradier units, so the swap guard still sees every bar writer"
metrics:
  duration: 35min
  completed: 2026-10-06
  tasks: 3
  files: 39
---

# Phase 189 plan 07: stop vendor 15m/1h and delete the nightly and lane machinery

Migration 445 takes vendor 15m and 1h out of every default fetch scope, and the nightly backfill, its units, the grid lane guard and the todo 449 lane machinery are deleted from the repo and the host with their tests. The IBKR history fetcher stays stopped and disabled.

## Task 0: migration 445 (662cc34e3)

- 445 was free (`ls production/migrations` ended at 441; 442, 443, 444 and 446 are reserved by 185-28, 185-31, 185-32 and 185-36).
- Applied live at 2026-10-06 23:55:55 UTC: `infra.backfill.default_scopes` is `{"compute_1d": ["1d", "5m"]}` and `infra.backfill.priority_tf_order` is `["5m"]`, both at version 2, with two `config_history` rows (changed_by `migration 445`). The header records the previous values and the rollback UPDATEs. The migration is idempotent (guards on the current value and an existing history row).
- `indicagent-ibkr-history-fetcher.timer` was already `disabled` (owner stop earlier on 2026-10-06), so no `systemctl disable` was needed; `indicagent-ibkr-history-fetcher.service` is inactive. Rollback for the timer is `sudo systemctl enable indicagent-ibkr-history-fetcher.timer` without `--now`.
- Fetcher `--dry-run` (read-only, no lock, no IBKR), output kept in the session scratchpad: 3004 candidate series. No 15m or 1h item. 1502 `5m` queued, 236 `1d` queued, 1266 `1d` held `tradier_owned`. The 5m items are the 189-10 pilot's queue and are not fetched until 189-10 enables the timer.
- The plan's automated verify passed (contract and migration-number tests, both config values, timer disabled).

## Task 1: nightly, units, lane guard and their tests (4a40e2f82)

Every leg of the nightly had a live caller before deletion (amendment 1):

| Nightly leg | Replacement |
|---|---|
| Tradier 1d leg (`--nightly`, APR switch) | `indicagent-tradier-daily.timer`, 01:30 UTC (189-06), enabled and active |
| `compute` leg (full stack) | IBKR history fetcher queue over `infra.backfill.default_scopes` (timer disabled until 189-10) |
| `compute_tradier_owned` (stack minus 1d) | fetcher holds Tradier-owned 1d series (`tradier_owned` in the dry run) |
| `compute_1d_only` | fetcher `compute_1d` scope at 1d (236 non-owned names queued) |
| split detection (`ops_split_detect.py`) | fetcher `_run_end_stages`, when a run touched 1d |
| daily stage (`bar_derivation --stage daily`) | fetcher `_run_end_stages`, then `refresh_1d_bounds` and `mark_fetch_complete` |
| grid stage (`--stage grid --changed-only --apply`) | fetcher `_run_end_stages`, when a run inserted 5m source rows |
| lane-guard exclude file | not needed: the fetcher's singleton lock means no concurrent IBKR writer |
| D7 audit (with `tradier_refused`) | `indicagent-bar-reconciliation-audit.timer`, 06:00 UTC (189-06), enabled and active |
| `logs/nightly_backfill_status.json` | written by the fetcher at run end (same `NIGHTLY_STATUS_FILE`) |
| `job_completed_total{job=nightly-backfill}` | `job=ibkr-history-fetcher` and `job=tradier-daily` |

While the fetcher is disabled (until 189-10), the IBKR legs, split detection, the daily and grid stages, and the status file do not run. Tradier names keep getting daily bars, and the 236 non-Tradier 1d names and all intraday get none. This is the owner's stop, not a regression introduced here.

Deleted with `git rm`: the nightly script, its service and timer, `ops_grid_lane_guard.py`, and `test_infrastructure_nightly_backfill.py`, `test_nightly_lease.py`, `test_grid_lane_guard.py`. Also deleted, beyond the plan's list (see deviations): `test_nightly_tradier_leg.py` (imports the nightly) and `tests/unit/scripts/conftest.py` (its only fixture patched the nightly module). Host: `/etc/systemd/system/indicagent-nightly-backfill.{service,timer}` removed (the wants symlink was already gone), daemon-reload, reset-failed. `ls /etc/systemd/system | grep -c nightly-backfill` prints 0 and `list-timers --all` has no nightly.

Grep evidence before deletion (`git grep` over everything except `.planning` and markdown, then the docs separately): the deleted names were referenced by the boundary allow-list, `ops_real_rows_swap.py` (consumer verdict, writer lists, runbook), `bar_reconciliation_audit.py` (comment), `ibkr_history_fetcher.py` (docstring), `tests/unit/scripts/conftest.py`, `test_nightly_tradier_leg.py`, `test_ops_real_rows_swap.py`, `infrastructure_run_historical_pipeline.py:46` (left for 189-08), three historical migrations (304, 344, 349; immutable), and the docs `operations-database.md`, `gotchas.md`, `services/overview.md`. Every live hit was rewritten or removed in the same commit. After the commit, the plan's grep over services, src, scripts, tests and production/systemd returns only `infrastructure_run_historical_pipeline.py:46`.

Wording: `bar_derivation.py`'s `--exclude-symbols-file` help and `_read_exclude_file` docstring describe an operator exclude list (option kept). The bar-derivation unit comment and both `service_auditor.py` comments say the fetcher runs the grid stage after a run that inserted 5m rows. The audit docstring names its own timer. The ops docs describe the three units in place of the nightly chain.

## Task 2: lane scripts, chain, retry loop, symbol lists (afc8e40bb)

- Precondition: 0 lane, chain or retry-loop processes.
- `quarantined.symbols` content, recorded here as operational history:

  ```
  HOOD
  # Quarantined 2026-10-01: head probe Error 162 + all data requests hang (60s client timeout, reqIds 4-13); AAPL probe on client 41 returned instantly, so path was healthy, HOOD-specific. Retry in a future lane run or re-qualify conId 504546674.
  ```

  HOOD's ledger rows now:

  | symbol | timeframe | consecutive_failures | last_fetch_status | last_fetched_at | latest_timestamp |
  |---|---|---|---|---|---|
  | HOOD | 1d | 0 | ok | 2026-10-01 08:42:17 UTC | 2026-10-02 |
  | HOOD | 1h | 0 | (null) | (null) | 2026-10-01 18:00 UTC |

  HOOD has no 5m or 15m row and is below `infra.backfill.max_consecutive_failures` (5). If its hang recurs in 189-10's 5m fetch, the ledger excludes it after 5 genuine failures; no file is needed (todo 484 superseded).
- `git rm` of the seven tracked files; `git ls-files logs/backfill_ops` prints nothing. The untracked `PAUSE_5M` marker was removed. The untracked attempt and watchdog logs, `intraday_chain.log`, `missing.symbols` and `zero_data.symbols` were left for log rotation.
- `src/providers/ibkr.py`'s timeout comment now names systemd's WatchdogSec on `indicagent-ibkr-history-fetcher.service` (and RuntimeMaxSec) as the external safety net. Comment only.
- `ops_real_rows_swap.py`: the writer-process list drops the four `.sh` names and adds `ibkr_history_fetcher.py`; runbook step 11 no longer relaunches the chain. Its test uses the fetcher as the matched writer process.
- Docs: the operations-database campaign block and the gotchas bullets no longer tell anyone to relaunch the chain or force-add under `logs/backfill_ops/`.
- Remaining grep hits: `infrastructure_run_historical_pipeline.py` (189-08), migrations 194 and 432 (immutable), and the integration seed fixture (a 2026-10-02 DB snapshot).
- Todo 452's two remaining items (factor the lane watchdog skeleton, decide the wrappers' home) are both superseded by this deletion; plan 09 closes it.

## Extra: deferred item 3 (3f100aaaf)

`indicagent-bar-reconciliation-audit.service`'s comment said "No timer". It now names the 06:00 UTC timer. The installed copy was updated to match (comment only, daemon-reload, timer still active).

## Commits

| Commit | What |
|---|---|
| 662cc34e3 | Task 0: migration 445 and its contract test |
| 4a40e2f82 | Task 1: nightly, units, lane guard and their tests deleted; references cleaned |
| afc8e40bb | Task 2: lane scripts, chain, retry loop and symbol lists deleted |
| 3f100aaaf | audit unit comment (189 deferred item 3) |

Plan 09's todo closure needs 4a40e2f82 and afc8e40bb.

## Verification

- Full `.venv/bin/pytest tests/unit/ -q`, after Task 1 and again after Task 2: exit 0, 8086 passed, 5 skipped (the same pre-existing skips), 0 failed. The count is lower than 185-44's 8137 by the deleted nightly, lease, lane-guard and Tradier-leg tests.
- Boundary family (every `tests/unit/test_*boundary*.py`), the three 185-44 guards (`test_temporary_allow_list_expiry.py`, `test_table_and_apr_key_readers.py`, `test_single_writer_registry.py`), `test_ops_real_rows_swap.py`, `test_tradier_daily_plan.py` and the 445 contract test: all pass after each commit. No orphaned table or APR key, so no `retire:` entry was needed (see deferred item 7 for the one 189-08 will orphan).
- vulture: no new finding versus HEAD before Task 1 (diffed in a scratch detached worktree, since removed).
- ruff and black clean on every touched Python file; pre-commit 9/9 on all four commits.
- Live: the Tradier daily and D7 audit timers are active and untouched; the fetcher timer is disabled and the service inactive; nothing was started.

## Deviations from plan

1. [Rule 3 - Blocking] Deleted `tests/unit/scripts/test_nightly_tradier_leg.py` and `tests/unit/scripts/conftest.py`, which were not in the plan's list. Both import or patch the deleted nightly. Three tests in the leg file tested surviving code and moved to `test_tradier_daily_plan.py` (amendment 2). Commit 4a40e2f82.
2. [Rule 3 - Blocking] `ops_real_rows_swap.py` and its test were edited (not in the plan's file list). The test requires the boundary allow-list and `CONSUMER_VERDICTS` to match, so the nightly's verdict had to go with its allow-list entry. The writer lists and the runbook named the deleted scripts. Commits 4a40e2f82 and afc8e40bb.
3. [Rule 2] `bar_reconciliation_audit.py` (comment and docstring), `ibkr_history_fetcher.py` (docstring) and three docs (`operations-database.md`, `gotchas.md`, `services/overview.md`) were edited so no live file names the deleted machinery as current. Required by the plan's grep criterion and the no-dangling-reference truth.
4. Task 0's `sudo systemctl disable` was skipped because the timer was already disabled.
5. Extra commit 3f100aaaf closes 189 deferred item 3, which asked plan 07 to fix that comment.
6. The first contract-test draft had a regex that matched across statements and failed. The migration was applied in the same command chain, before the test was fixed (the migration itself was correct; the failure was in the test helper). The test was fixed before commit and passes.

## Deferred (added to deferred-items.md)

- Item 6: live `config_schema` descriptions of `infra.ibkr.historical_request_timeout_sec` and `infra.backfill.default_scopes` still cite the retry loop, the nightly legs and PAUSE_5M.
- Item 7: `infra.ibkr_history_lease.nightly_wait_minutes` keeps a reader only through the historical pipeline's help text; 189-08 must add a `retire:` entry or delete it when it absorbs that script.
- Item 8: the D7 `nightly_skipped` check reports a finding every day while the fetcher is disabled; it clears after 189-10.

## For the next plans

- 185-28 (migration 442) and 185-31 (migration 443): numbers still free. 185-31 can edit `services/bar_derivation.py`, `services/bar_reconciliation_audit.py` and `tests/unit/test_market_data_ohlcv_boundary.py` now; all three are committed and clean. In `bar_derivation.py`, 189-07 changed only the exclude-file help and the `_read_exclude_file` docstring. In `bar_reconciliation_audit.py`, it changed only the module docstring and the `NIGHTLY_STATUS_FILE` comment.
- 185-31 no longer has a lane guard to consult, and `tests/unit/scripts/conftest.py` is gone; a new scripts test that drives the fetcher's run-end stages must inject `stage_runner` (gotchas updated).
- 189-10 inherits the queue shown above: 1502 5m series ranked by priority, plus 236 1d.

## Known stubs

None.

## Threat flags

None. Sudo use was limited to removing the nightly unit files, copying the audit unit and daemon-reload / reset-failed.

## Self-Check: PASSED

- FOUND: production/migrations/445_backfill_scopes_stop_vendor_htf.sql, tests/unit/test_backfill_scopes_migration_contract.py
- GONE: all 16 deleted paths (`test ! -e`), `/etc/systemd/system/indicagent-nightly-backfill.*`, `logs/backfill_ops/PAUSE_5M`
- FOUND commits: 662cc34e3, 4a40e2f82, afc8e40bb, 3f100aaaf
