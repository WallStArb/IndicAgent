---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 03
subsystem: backfill
tags: [ibkr, fetcher, coverage-ledger, stall-bound, gap-planner, d1]
requires: [189-01, 189-02, 185-18, 185-19, 185-22]
provides:
  - "_history_fetch_item.py: ItemOutcome, ProgressClock, ItemStalled, GatewayLost, FetchContext, run_with_stall_bound, fetch_item, fetch_item_with_retries"
  - every non-1d provider chunk persisted atomically with its request rows and CoverageDelta
affects: [189-04, 189-06, 189-08]
tech-stack:
  added: []
  patterns:
    - "progress-aware asyncio.wait_for(asyncio.shield(task)) stall check instead of a whole-item deadline"
    - "per-run caches on FetchContext (qualified, heads_checked, fx_derived) replace the per-symbol loop's implicit grouping"
key-files:
  created: []
  modified:
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - tests/unit/scripts/test_history_fetch_item.py
    - tests/unit/test_ibkr_history_lease_boundary.py
decisions:
  - "fetch_item follows the pipeline loop body as it stands after 185-18/19/22, not the plan text: 1d is D1-only and never persists, so the 1d grid CoverageDelta the plan described does not exist"
  - "A 1d item returns derive_1d_since; the caller runs the daily derivation stage and marks 1d fetch_complete, as the pipeline does after its loop"
  - "fetch_per_contract storing zero bars is 'error', not 'no_data': it swallows per-contract exceptions, so an empty result cannot be told from a failure"
  - "The head-lookup single-request test is per timeframe (the item's own), not across the run's whole timeframe set"
metrics:
  tasks: 2
  completed: 2026-10-06
---

# Phase 189 Plan 03: Fetching one (symbol, timeframe) item summary

`fetch_item` is the pipeline's per-(symbol, timeframe) loop body as a tested unit. It plans
through 185-18's shared gap planners, commits every non-1d provider chunk atomically with its
request rows and ohlcv_coverage delta, and classifies the outcome as ok, no_data or error.
`fetch_item_with_retries` wraps it in a progress-aware stall bound with reconnect and bounded
retries, so one silent socket cannot hang the run.

## Commits

| Task | Gate | Commit | What |
|------|------|--------|------|
| 1 | RED | 02d1a57d7 | failing tests for the stall bound and retries |
| 1 | GREEN | d0d0bd39b | ProgressClock, ItemStalled, run_with_stall_bound, fetch_item_with_retries |
| 2 | RED | c57e837ef | failing tests for fetch_item (pre-185-18 rules, see deviations) |
| 2 | GREEN | c1f14c3d8 | fetch_item, FetchContext, tests rewritten for current rules, lease allow-list |

## Verification

`.venv/bin/pytest tests/unit/scripts/test_history_fetch_item.py tests/unit/scripts/test_intraday_persist.py tests/unit/test_market_data_ohlcv_boundary.py tests/unit/test_ibkr_history_lease_boundary.py tests/unit/scripts/test_historical_pipeline_d1_capture.py tests/unit/scripts/test_fetch_queue.py -q`: 136 passed. The item test file alone runs in under 2 s. mypy reports no errors in `_history_fetch_item.py`; ruff and black are clean. `infrastructure_run_historical_pipeline.py` is untouched.

`tests/unit/test_market_data_ohlcv_writer_boundary.py` fails, but not because of this plan.
It flags `scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py` (commit
2e3a90f37, the Tradier loader, owned by phase 185), which is not on the writer allow-list.
`_history_fetch_item.py` matches neither boundary pattern, so both allow-lists stay
unchanged. The Tradier entry belongs to the phase 185 session.

## Interface finalized for 189-04

- `FetchContext(provider, settings, connect, sink, fetch_run_id, tf_fetch_config, end_dt, run_started_at, empty_ranges, empty_reverify_days, fresh_heads, first_bars, days_override=None, per_contract=False, overlap_sessions=0)`. `connect` returns a new autocommit psycopg connection (`connect_db(settings)`). `get_conn()` runs the SELECT 1 probe and reconnects. The per-run caches are `qualified`, `heads_checked` and `fx_derived`. `fresh_heads` is mutated in place when a head lookup succeeds.
- `fetch_item_with_retries(ctx, instrument, row, *, gap_days, full_scan, config, reconnect, on_tick=None) -> ItemOutcome`. `row` is a `_fetch_queue.CoverageRow`, `gap_days` is the `RankedItem.gap_days`, and `config` is `QueueConfig`. `on_tick` runs on every stall check (every `history_request_timeout_s / 3`); wire the systemd watchdog notify to it.
- `ItemOutcome`: `status`, `n_bars`, `n_grid_source_rows` (5m rows written, derived FX rows included), `attempts`, `gateway_lost`, `error`, `elapsed_s`, `derive_1d_since`.
  - When `gateway_lost` is set, do not call `record_fetch_outcome` (CD-05).
  - When `derive_1d_since` is set, collect the symbol. After the queue drains, run the daily derivation stage (`_run_daily_stage`) over the collected symbols, then call `mark_fetch_complete(conn, symbol, "1d", since)`. Only mark items whose status was ok.
  - Promote the derived 15m/1h grid when `n_grid_source_rows > 0`.
- The item flushes the D1 sink itself. The main loop still owes the pipeline's best-effort final flush when `sink.pending()` is set, because an unexpected exception skips the item's own flush.
- `fetch_item` itself raises `GatewayLost` and lets a sink-flush failure raise. Only `fetch_item_with_retries` turns these into outcomes, so always call the wrapper.

## Open questions for 189-04 (design, not decided here)

1. **The 1d coverage ledger never moves.** `fetch_item` cannot write 1d bars, because D2 is the sole 1d writer and `store_bars` refuses 1d. So no `persist_chunk_atomically` call ever updates the 1d `ohlcv_coverage` bounds or row_count. Only the item's `record_fetch_outcome` status reaches the ledger, which leaves `latest_timestamp` for 1d frozen at the 189-01 bootstrap. Correctness holds, because the D1 planner skips answered sessions and a stale tail start only widens the window. Queue staleness and SLA ranking for 1d, however, read that column. One option is for the daily derivation stage to call `ohlcv_coverage_writer.upsert_coverage` inside its own transaction, which keeps a single writer module. The other is for the fetcher to refresh 1d bounds after the stage. Decide this in 189-04.
2. **Tradier owns 1d.** It is the primary 1d source (owner decision 2026-10-03, migration 438), with a one-source-per-name rule, and plan 185-26 adds a Tradier-owned skip to the IBKR nightly. The fetcher's queue has to apply the same skip, or drop 1d for Tradier-owned names. The skip belongs in queue loading, not in `fetch_item`.
3. **1d overlap for split detection (185-22).** The nightly passes `--overlap-sessions` and runs a split-judging step after the fetch. `FetchContext.overlap_sessions` carries the fetch half. The split-judge, re-fetch and re-derive step is run-level and is not ported.
4. **Todo 490** (P1, open from 185-18): the grid stage fails on revised bars. 185-18 flagged it for a decision before 189-04.

## Deviations from plan

### Reconciled with plans 185-18, 185-19 and 185-22, which landed after this plan was written

1. **1d no longer persists anything.** The plan described 1d chunks going through `persist_chunk_atomically` with a grid `CoverageDelta`, plus a 1d placeholder fill. After 185-18 task 1b, 1d answers are D1 rows only: requests and observations flush through the sink, `on_chunk` is None, and `store_bars` refuses 1d. `fetch_item` keeps that behaviour and adds `derive_1d_since` so the caller can run the daily stage. The plan's must-have "every provider chunk ... for 1d ... persisted through persist_chunk_atomically" cannot hold, and nothing in the item now writes 1d coverage (open question 1).
2. **The shared gap planners replace `detect_gaps` for most timeframes.** 5m, 15m and 1h now plan through `_d1_gaps.detect_gaps_from_record` with `expected_grid_slots`, and 1d through `detect_gaps_1d_from_d1` over `nyse_sessions`; a non-NYSE 1d name raises, as in the pipeline. Only 1m and 4h stay on the legacy `detect_gaps` plus `apply_empty_range`. `load_answered_windows` now comes from `_d1_gaps`, because `_request_coverage.py` was deleted in 185-18.
3. **Request window ends.** The record and D1 planners return end-exclusive windows, so the request is sent as planned. Only 1m extends to the end of its last slot, capped at `end_dt`. The plan's "extend by one interval under real-bars-only" applied to the old inclusive ranges.
4. **There is no `real_bars_only` flag.** 185-18 retired it, and `real_bars_only_for(tf)` is a fixed per-timeframe set. The placeholder path (normalize, then `store_bars` with the synthetic fill outside coverage) is now reachable only for 4h.
5. **1d empty history (185-19).** The oldest non-continuous 1d window sets a flag. After the item's flush, `empty_history.reconcile_empty_history(conn, "1d", "ibkr", symbols=[symbol])` runs. Other timeframes keep the in-walk `empty_history.reconcile`.
6. **The FX/crypto fallback never derives 1d.** 185-18 removed 1d from that fallback. Each item derives only its own timeframe from the stored 1m, and the deep 1m fetch still runs once per symbol per run. The deep fetch now records its requests (the pipeline passed no capture kwargs there) and persists atomically with 1m grid coverage.
7. **The task 2 RED tests were rewritten.** c57e837ef was committed about 6 hours before 185-18 task 1b (8b2e5f6d7) and encoded the retired model: 1d stored to the grid, a 1d placeholder fill, and 15m planned by `detect_gaps`. Part 1 (task 1) is unchanged. Part 2 now patches all three planners and tests the current rules.

### Other deviations

- **[Rule 1] Derived 5m rows are counted in `n_grid_source_rows`.** The first green run showed that FX-derived 5m rows were missing from the count, which would have kept the derived 15m/1h grid from being promoted. Fixed in c1f14c3d8.
- **[Rule 2] `fetch_per_contract` returning zero bars is `error`.** It prints and swallows each contract's exception, so classifying zero bars as `no_data` would reset the failure counter on a real failure.
- **[Rule 2] Returned bars that missed `on_chunk` are still persisted.** The provider sends every chunk to `on_chunk` today. Any returned bar that did not pass through it is still persisted atomically with coverage, keyed on the timestamps already persisted.
- **The lease guard allow-lists the module.** The entry is `_history_fetch_item.py` with the plan's TEMPORARY reason. The file had no other session's hunk when it was committed.
- **The task 1 return path is typed.** `outcome: ItemOutcome` clears a mypy `no-any-return` in `fetch_item_with_retries`.

## Ported d1-capture tests

Each port in `tests/unit/scripts/test_history_fetch_item.py` is named after its source test in `tests/unit/scripts/test_historical_pipeline_d1_capture.py`:

| Port | Source |
|------|--------|
| test_port_capture_and_checkpoint_wiring | test_capture_and_checkpoint_wiring |
| test_port_15m_is_archive_bound_and_1d_is_d1_only | test_15m_is_archive_bound_and_1d_is_d1_only |
| test_port_1d_fetch_captures_to_d1_and_persists_no_chunk | test_1d_fetch_captures_to_d1_and_persists_no_chunk |
| test_port_daily_stage_runs_for_touched_symbols_on_the_clean_path | test_daily_stage_runs_for_touched_symbols_on_the_clean_path (item half: derive_1d_since) |
| test_port_5m_chunks_persist_atomically_into_the_grid | test_5m_chunks_persist_atomically_into_the_grid |
| test_port_15m_always_asks_through_the_last_slot_end | test_15m_always_asks_through_the_last_slot_end |
| test_port_flush_failure_fails_the_symbol_loudly | test_flush_failure_fails_the_symbol_loudly |
| test_port_1d_empty_history_is_reconciled_from_d1_after_the_flush_not_from_the_walk | same name |
| test_port_overlap_sessions_adds_the_recent_sessions_window_to_each_1d_symbol | same name |
| test_port_no_overlap_by_default | test_no_overlap_by_default |
| test_port_a_caller_supplied_fetch_run_id_labels_every_request | same name |

Not ported:
- **Lease cases** (`test_priority_tier_flag_reaches_the_lease`, `test_lease_timeout_exits_with_the_lease_code`, `TestLeaseWaitSeconds`). Plan 08 retires the lease.
- **`test_daily_stage_failure_fails_the_run_loudly`.** This is run-level and belongs to 189-04's main loop.
- **Helper unit tests** (`test_store_bars_refuses_1d`, `test_real_bars_only_now_covers_1d`, `TestCaptureKwargs`). They test pipeline helpers that move in plan 08.

## Known stubs

None.

## Threat flags

None. The module adds no new endpoint, auth path or schema; it writes through the existing atomic persist helper and coverage writer.

## Self-Check: PASSED

- FOUND: scripts/infrastructure/backfill/_history_fetch_item.py
- FOUND: tests/unit/scripts/test_history_fetch_item.py
- FOUND commits: 02d1a57d7, d0d0bd39b, c57e837ef, c1f14c3d8
