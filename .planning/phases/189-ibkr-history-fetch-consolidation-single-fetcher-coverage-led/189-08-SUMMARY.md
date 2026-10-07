---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 08
subsystem: ibkr-history-backfill
tags: [deletion, rename, ci-guard, apr, migration-434, CD-01, CD-09, CD-11, data-layer-integrity]
requires: [189-07, 185-28, 185-32, 185-39, 185-41]
provides:
  - "scripts/infrastructure/backfill/_history_fetch.py: the former pipeline's helpers, no CLI, no lease, no legacy ranking, no backfill_status writer"
  - "ibkr_history_fetcher.py is the only IBKR history CLI; --overlap-sessions override; named --symbols bypass the current hold"
  - "tests/unit/test_ibkr_history_lock_boundary.py: every IBKR history fetch caller references FetcherLock in code or is allow-listed"
  - "migration 434: infra.ibkr_history_lease.* retired (live 2026-10-07)"
  - "todos 506 (factory takes FetcherLock after 186-26) and 507 (in-process split re-fetch, P1, gate 189-10 Task 1b)"
affects: [189-09, 189-10, 185-37, 185-42, 185-43, 185-48]
tech-stack:
  added: []
  patterns: ["a CI lock guard matches the marker in code (AST), not in prose"]
key-files:
  created:
    - production/migrations/434_retire_ibkr_history_lease_apr.sql
    - tests/unit/test_retire_ibkr_history_lease_apr_migration_contract.py
    - .planning/todos/pending/506-backfill-feature-factory-fetch-only-fetcher-lock.md
    - .planning/todos/pending/507-split-refetch-in-process-under-the-fetcher-lock.md
  renamed:
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py -> scripts/infrastructure/backfill/_history_fetch.py
    - tests/unit/scripts/test_run_historical_pipeline.py -> tests/unit/scripts/test_history_fetch.py
    - tests/unit/test_ibkr_history_lease_boundary.py -> tests/unit/test_ibkr_history_lock_boundary.py
  modified:
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - scripts/infrastructure/backfill/_fetcher_lock.py
    - scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
    - scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py
    - scripts/ops/bars/ops_head_rerun.py
    - scripts/ops/bars/ops_split_detect.py
    - scripts/ops/bars/ops_intraday_venue_recovery.py
    - scripts/ops/bars/ops_real_rows_swap.py
    - src/providers/ibkr.py
    - src/providers/CLAUDE.md
    - tests/unit/scripts/test_history_fetch_item.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py
    - tests/unit/scripts/test_head_rerun.py
    - tests/unit/scripts/test_ops_split_detect.py
    - tests/unit/scripts/test_tradier_daily_run.py
    - tests/unit/scripts/test_ops_real_rows_swap.py
    - tests/unit/core/test_resource_lease.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_market_data_ohlcv_no_synthetic_fill.py
    - tests/unit/test_ohlcv_load_revision_writer_boundary.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_temporary_allow_list_expiry.py
    - tests/integration/test_ingress_write_contract.py
    - tests/integration/test_ops_real_rows_swap_scratch.py
    - .planning/todos/PRIORITIES.md
    - .planning/todos/pending/499-drop-normalize-bars-and-move-gap-readers-to-coverage-ledger.md
  deleted:
    - scripts/debug/replay/debug_replay_all.sh
    - scripts/ops/bars/ops_tradier_fetch_complete_repair.py
    - tests/unit/scripts/test_historical_pipeline_d1_capture.py
    - tests/unit/scripts/test_ops_tradier_fetch_complete_repair.py
decisions:
  - "The split re-fetch moves onto the fetcher CLI and fails loudly (exit 3) when the fetcher's own lock refuses it; the in-process re-fetch is todo 507 for 189-10 Task 1"
  - "Named --symbols bypass the fetcher's current hold, and the ops callers pass --full-scan, so a caller that names a series gets it asked (otherwise both ops tools would silently ask nothing)"
  - "The Tradier loader stops writing backfill_status.fetch_complete with the writer's deletion; promotion reads verdicts since 185-41"
  - "Todo 499 stays open: closing it would fail the 185-44 expiry guard on bar_normalizer's entry (185-42's) and drop its unplanned gap-reader step"
metrics:
  duration: 80min
  completed: 2026-10-07
  tasks: 2
  files: 44
---

# Phase 189 plan 08: the pipeline becomes a helper library; the fetcher lock is the only primitive

`infrastructure_run_historical_pipeline.py` is now `_history_fetch.py`, a helper library with no CLI, no lease, no legacy gap ranking and no backfill_status writer; `ibkr_history_fetcher.py` is the only IBKR history CLI, CI requires `FetcherLock` of every IBKR history caller, and migration 434 retired the two lease APR keys live.

## Preconditions

- `ps -eo pid,args | grep -E '[b]ackfill_feature_factory|[i]ntraday_chain|[i]bkr_history_fetcher|[i]nfrastructure_run_historical_pipeline'`: no output, before the first edit and again before the first commit.
- `indicagent-ibkr-history-fetcher.timer` disabled and inactive, service inactive. Nothing was started.
- Migration 434 was free (430-433 and 435-455 present, 434 absent).

## Task 1: rename, strip, re-point (1be02ae51)

- `git mv` to `_history_fetch.py`, then deleted: `main()` and the `__main__` block (with `_run_daily_stage`, which only `main` used), argparse, `_DEFAULT_TIMEFRAMES`, `_DIMENSIONS_REQUIRING_EXPLICIT_TIMEFRAMES` (the fetcher already owns `validate_args`), `IBKR_HISTORY_LEASE`, `EXIT_LEASE_TIMEOUT`, `_LEASE_APR_KEY`, `_LEASE_PRIORITY_MINUTES_FALLBACK`, `_load_lease_apr_minutes`, `_lease_wait_seconds`, `_acquire_history_lease`, the ResourceLease import, `_reorder_contracts_by_gap`, and (amendment 3) `mark_fetch_complete` with its SQL. The sys.path bootstrap is gone: every importer imports it as a package module. New module docstring; the stale nightly comments now name the fetcher's stages. The 185-32 and 185-39 edits (real bars only, write contract) came across untouched.
- Item fetch: imports `_history_fetch`; the unreachable placeholder branch (`normalize_bars` + `store_bars`), its `_bar_dict` helper and the `mark_fetch_complete` call are gone.
- Fetcher: imports `_history_fetch`; `_finish_1d` only refreshes the 1d ledger bounds; `Candidates.scope_contracts` (no reader, todo 499) dropped; `--overlap-sessions` (validated non-negative) overrides the APR overlap; `--symbols` sets `current_after=None` so named series are asked even when current (see deviations).
- Callers: `ops_head_rerun.py` and `ops_split_detect.py` drive the fetcher (moved here from Task 2, see deviations); the probe and `ops_intraday_venue_recovery.py` import `_history_fetch`; `infrastructure_run_tradier_daily.py` no longer imports or calls `mark_fetch_complete`; `infrastructure_reset_pipeline_data.py` lost `_run_backfill` and its call (the lifecycle replay and wipe stay); `debug_replay_all.sh` deleted; `ops_real_rows_swap.py`'s consumer verdict key renamed and the dead process name dropped; comments in `src/providers/ibkr.py` (~119), `universe_expansion_fetch_iwv_holdings.py` and `src/providers/CLAUDE.md` name `_history_fetch.py` and the fetcher.
- Allow-lists: `test_market_data_ohlcv_boundary.py`, `test_market_data_ohlcv_writer_boundary.py` (entry and `_FENCE_EXEMPT`) renamed with rewritten PERMANENT reasons; the `_history_fetch_item.py` entry left `test_market_data_ohlcv_no_synthetic_fill.py` (`_NORMALIZE_CALLERS` is empty). `test_bar_write_no_first_write_wins.py` and `test_single_writer_registry.py` held no pipeline entry; `test_ohlcv_load_revision_writer_boundary.py` had one prose mention, updated.
- `git log --follow -M40% scripts/infrastructure/backfill/_history_fetch.py` shows 151 commits (see deviations for the default threshold).

### d1-capture test mapping

Every case of the deleted `tests/unit/scripts/test_historical_pipeline_d1_capture.py`:

| Source test | Now |
|---|---|
| test_capture_and_checkpoint_wiring | test_history_fetch_item.py::test_port_capture_and_checkpoint_wiring |
| test_15m_is_archive_bound_and_1d_is_d1_only | test_history_fetch_item.py::test_port_15m_is_archive_bound_and_1d_is_d1_only |
| test_1d_fetch_captures_to_d1_and_persists_no_chunk | test_history_fetch_item.py::test_port_1d_fetch_captures_to_d1_and_persists_no_chunk |
| test_daily_stage_runs_for_touched_symbols_on_the_clean_path | test_history_fetch_item.py::test_port_daily_stage_runs_for_touched_symbols_on_the_clean_path (item half) and test_ibkr_history_fetcher.py::test_1d_items_run_split_detection_daily_stage_then_refresh_the_ledger (run half) |
| test_daily_stage_failure_fails_the_run_loudly | test_ibkr_history_fetcher.py::test_failed_daily_stage_skips_the_ledger_refresh_and_is_partial |
| test_store_bars_refuses_1d | test_history_fetch.py::test_store_bars_refuses_1d (ported now) |
| test_real_bars_only_now_covers_1d | test_history_fetch.py::TestArchiveGridRouting::test_real_bars_only_for_every_tf (covers 1d and 4h) |
| test_5m_chunks_persist_atomically_into_the_grid | test_history_fetch_item.py::test_port_5m_chunks_persist_atomically_into_the_grid |
| test_15m_always_asks_through_the_last_slot_end | test_history_fetch_item.py::test_port_15m_always_asks_through_the_last_slot_end |
| test_flush_failure_fails_the_symbol_loudly | test_history_fetch_item.py::test_port_flush_failure_fails_the_symbol_loudly |
| test_1d_empty_history_is_reconciled_from_d1_after_the_flush_not_from_the_walk | test_history_fetch_item.py::test_port_ (same name) |
| test_overlap_sessions_adds_the_recent_sessions_window_to_each_1d_symbol | test_history_fetch_item.py::test_port_ (same name) |
| test_no_overlap_by_default | test_history_fetch_item.py::test_port_no_overlap_by_default |
| test_a_caller_supplied_fetch_run_id_labels_every_request | test_history_fetch_item.py::test_port_ (same name) |
| TestCaptureKwargs (2 tests) | test_history_fetch.py::TestCaptureKwargs (ported now) |
| test_priority_tier_flag_reaches_the_lease, test_lease_timeout_exits_with_the_lease_code, TestLeaseWaitSeconds (3) | retired with the lease |

`test_history_fetch.py` dropped the CLI tests (three partial-stack `main()` tests; `validate_args` is covered by `test_explicit_scope_flags_resolve_one_scope_and_keep_the_timeframes_rule`), the `mark_fetch_complete` test and the `--normalize` CLI test, which became `test_the_pipeline_cli_lease_and_legacy_ranking_are_gone`.

## Task 2: guard, lease cleanup, migration 434 (1be02ae51 and 3597da3a1)

- `ops_head_rerun.py` (in 1be02ae51): `_FETCHER`, `fetcher_command()` builds `--symbols --timeframes 1d --dimension compute_1d --client-id 49 --full-scan`; `_run_chunk` maps the exact `LOCK_HELD_MESSAGE` line to `_LOCK_HELD_EXIT = 3` and prints "fetcher lock held: stopping cleanly; rerun resumes (resolved names skipped)". Three new tests.
- Lock guard (in 1be02ae51): `git mv` to `test_ibkr_history_lock_boundary.py`. Callers of `fetch_historical_bars`, `fetch_adjusted_daily_closes` or `get_head_timestamp` must reference `FetcherLock` in code, checked by AST so a docstring mention does not count. Allow-list: the three providers (PERMANENT), `_history_fetch.py` and `_history_fetch_item.py` (PERMANENT), `services/backfill_feature_factory.py` (TEMPORARY, `retire: todo 506`). Stale-entry check kept; a ResourceLease-free check added. The two frozen clause-less entries in `test_temporary_allow_list_expiry.py` are gone (the frozen dict is empty).
- `test_resource_lease.py` (3597da3a1): the ibkr_history_stream pin became a generic sha256 key vector; the docstring sentence names FetcherLock as the IBKR primitive; every generic test stays and passes.
- Migration 434 (3597da3a1): contract test first (failed, then passed). Deletes both keys from history, state and schema in one transaction. Applied live at 2026-10-07 18:33:25 UTC with `lock_timeout 10s`: `DELETE 2` three times; `config_state`, `config_schema` and `config_history` now hold 0 rows for `infra.ibkr_history_lease.%`. Task 1 had parked both keys in `_PENDING_RETIREMENT` (`retire: 189-08`); 3597da3a1 removed the entries with the keys. `test_ohlcv_observation_migration_contract.py` reads migration 380's file only, so it needed no change.
- `_fetcher_lock.py` docstring and `ops_real_rows_swap.py`'s `WRITER_LOCK_NAMES` (now only the fetcher lock; unit and integration tests updated) no longer name the retired lease.
- Todo 506 filed with its P3 row; link integrity passes.

## Verification

- Full `.venv/bin/pytest tests/unit/ -q`: 8434 passed, 5 skipped after Task 1; 8439 passed, 5 skipped after Task 2 (the same five pre-existing skips).
- Plan verify: the Task 2 command list passes and `grep -rln 'ibkr_history_stream\|ibkr_history_lease' services src scripts` is empty; `lease-tier` too.
- `grep -c "def main\|_reorder_contracts_by_gap\|ResourceLease\|IBKR_HISTORY_LEASE\|EXIT_LEASE_TIMEOUT" _history_fetch.py` is 0.
- `grep -rln infrastructure_run_historical_pipeline services src scripts tests production` lists only immutable migrations (186, 227, 276, 304, 313, 354, 432) and the dated `tests/integration/fixtures/seed_config_2026-10-02.sql` snapshot.
- ruff and black clean on every touched file; pre-commit 9/9 on both commits. The one ruff finding repo-wide (`tests/unit/research_tools/test_repro_frozen.py`, import order) predates this plan and was left alone.
- No `src/intelligence/research` or `statistics` edit, so repro_frozen does not apply.

## Deviations from plan

1. [Rule 3 - Blocking] Callers outside the file list. `ops_split_detect.py` (the fetcher's own split stage launched the pipeline CLI; 189-04-SUMMARY item 4 assigned the rewire to 07/08), `infrastructure_run_tradier_daily.py` and `ops_tradier_fetch_complete_repair.py` (imported the deleted `mark_fetch_complete`), `infrastructure_ibkr_chunk_and_rate_limit_probe.py`, `ops_intraday_venue_recovery.py`, `ops_real_rows_swap.py`, `src/providers/CLAUDE.md`, and their tests plus two integration tests. Without them the tree would not import or the plan's grep would not be empty.
2. [Rule 1 - Bug] Split re-fetch under the fetcher lock. Pointing the re-fetch at the fetcher CLI means a split found inside a fetcher run is refused by the parent's own lock. The child exits 0, so `run_refetch` maps the `LOCK_HELD_MESSAGE` line to exit 3: the derivation is skipped, the run ends partial, and D2 keeps the bars quarantined (`pre_split_unrefetched`) until `--refetch-only` runs. It never reads as a success. The in-process fix is todo 507 (P1, gate: before 189-10 Task 1b's refresh step).
3. [Rule 1 - Bug] The fetcher's `current` hold and tail planning would make both ops callers ask nothing for a current, gap-free series, and the split re-fetch would return 0 having re-fetched nothing. Named `--symbols` now bypass the hold, and both callers pass `--full-scan` (the pipeline always planned the full window). The timer run names no symbols, so its behavior is unchanged. `--overlap-sessions` was added to carry the split depth, absorbing the pipeline's flag of the same name.
4. [Rule 3] Task ordering. `ops_head_rerun.py`, the lock-guard rename and rewrite, and todo 506 landed in the Task 1 commit, because the Task 1 tree would otherwise reference a deleted file, fail the old lease guard (`_history_fetch.py` lost its ResourceLease) and fail the 185-44 reader guard. The two lease keys sat in `_PENDING_RETIREMENT` for one commit for the same reason.
5. The Tradier loader stops writing `fetch_complete` (it imported the deleted writer). It is disabled (185-46) and deleted by 185-48; promotion reads verdicts since 185-41. `ops_tradier_fetch_complete_repair.py` (a one-off already applied 2026-10-06, scheduled for deletion by 185-42) was deleted with its test.
6. Todo 499 is not closed (amendment 3 says close it). Its step 1 is done; closing it would fail `test_temporary_allow_list_expiry.py` on `src/core/bar_normalizer.py`'s `retire: todo 499` entry (185-42 deletes normalize_bars), and its step 3 (gap readers onto `ohlcv_coverage`) has no plan. A progress section and the PRIORITIES row record the state.
7. `git log --follow` with git's default 50% rename threshold shows 1 commit, not more than 5: the rename commit removed more than half of the file (main alone was about 1,000 lines), so git scores it 41% similar. `git log --follow -M40%` shows all 151 commits. A pure-rename commit first would have kept the default; the history is intact and was not rewritten.
8. `test_resource_lease.py`'s key-vector test became generic rather than deleted, so the sha256 derivation stays pinned.
9. The plan's Task 1 grep includes `production`, whose remaining hits are immutable migrations and a dated DB snapshot fixture (deferred item 10).

## Deferred (added to deferred-items.md)

- Item 7 resolved (lease keys retired).
- Item 9: root `CLAUDE.md` (owner file; executors do not edit it) still says every history fetch takes the `ibkr_history_stream` lease; `docs/reference/gotchas.md`, the onboarding SOP, `config/universe/README.md` and other docs name the deleted script, lease or repair tool. For 189-09 (and 185-43 for the SOP's backfill_status wording).
- Item 10: the integration seed fixture snapshot still holds the retired keys.

## For the next plans

- 189-10 Task 1 (two-lane queue, migration 451): its amendment block says the lanes "share the fetcher, the ibkr_history_stream lease and the request ledger"; the lease no longer exists, so read that as FetcherLock. Todo 507 belongs there: the overlap escalation and the split re-fetch should be one in-process path, ordered record, re-fetch, derive (D2 counts only a fetch made after the recording). Named `--symbols` now bypass the current hold (Task 1b's "refresh every remaining active name" relies on it), and `--overlap-sessions` exists on the CLI. `_finish_1d` no longer writes backfill_status. Deferred item 6 (APR descriptions naming deleted machinery) still wants a description UPDATE in 451.
- 185-37: no backfill_status write remains on the fetch path or in the Tradier loader. The fetch helpers are imported from `scripts.infrastructure.backfill._history_fetch`.
- 185-42: `ops_tradier_fetch_complete_repair.py` is already gone; `_insert_market_data_rows` lives in `_history_fetch.py`; the last `normalize_bars` call is gone, so its precondition holds.
- 185-43: drop `_history_fetch.py` and the fetch path from its backfill_status reader list (189-08 removed them).

## Known stubs

None.

## Threat flags

None. T-189-27 mitigated by the lock guard; T-189-28 by the reader grep in migration 434's header and its contract test; T-189-29 accepted with todo 506.

## Self-Check: PASSED

- FOUND: _history_fetch.py, test_history_fetch.py, test_ibkr_history_lock_boundary.py, migration 434, its contract test, todos 506 and 507
- GONE: infrastructure_run_historical_pipeline.py, test_run_historical_pipeline.py, test_ibkr_history_lease_boundary.py, test_historical_pipeline_d1_capture.py, debug_replay_all.sh, ops_tradier_fetch_complete_repair.py and its test
- FOUND commits: 1be02ae51, 3597da3a1 (both pushed)
