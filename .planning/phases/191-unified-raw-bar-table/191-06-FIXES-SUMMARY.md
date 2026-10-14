---
phase: 191-unified-raw-bar-table
plan: 06
type: fixes
subsystem: bar data layer
tags: [gap-planner, 1d, head-floor, coverage-ledger, 1h-grid]
requires: [191-06]
key-files:
  modified:
    - scripts/infrastructure/backfill/_d1_gaps.py
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - scripts/infrastructure/backfill/_empty_history.py
    - scripts/infrastructure/backfill/_fetch_queue.py
    - scripts/infrastructure/backfill/ohlcv_history_fetcher.py
    - services/ohlcv_coverage_writer.py
    - src/intelligence/bars/gap_plan.py
  created:
    - production/migrations/478_provider_head_kind_floor.sql
    - tests/unit/test_provider_head_kind_migration_contract.py
key-decisions:
  - a 1d window is never capped at now; only closed sessions are planned
  - a seeded tape floor is a floor (head_kind 'floor'), only a successful lookup is a head
  - the first bar is read lazily per series, not for the whole queue at startup
  - the 1h grid is the opening bar then clock hours; a slot ends where its bar ends
metrics:
  completed: 2026-10-14
---

# Phase 191 Plan 06 review fixes Summary

Review of 886e9c212 found three high findings (1d asked only after 00:00 UTC and re-queued every run, a startup read of hours, seeded floors posing as heads), two medium and three low. All but findings 6 and 10 are fixed; those two are recorded in todo 535.

Commits (all on main, not pushed): `4094da9b7` (finding 1), `0b8d3aa73` (findings 2, 3, 7), `0e91abb4c` (finding 4), `129252fb5` (finding 5), `1852a8961` (finding 8 and the provider constant), plus the docs commit for this summary, the 06 summary correction (finding 9) and todo 535.

## Finding 1: the 1d planner and the overlap window

`detect_gaps_1d_from_d1` plans only sessions that have closed (`session_complete_at(day, now, sessions)`) and ends its horizon at midnight of the last session plus one day, never at `now`. `with_overlap_window` appends an end-exclusive window (first session, last session + 1 day) and merges on `start <= prev_end`. The fetch item hands it only closed sessions (`_closed_sessions`), so a forming session is never re-asked either. The test that asserted the zero-length `(D2, D2)` window is replaced by one that asserts no plan mid-session and `(D2, D3)` after the close.

Proof with the review's simulation (real code, fake connection, stored through Friday 10-09, Monday 10-12 session closes 20:00 UTC):

| now (UTC) | plan | overlap window end |
|---|---|---|
| 10-12 19:00 (live check, session open) | none | 10-12 (the prior session) |
| 10-12 20:00 | (10-12, 10-13) | 10-13 |
| 10-12 22:00 | (10-12, 10-13) | 10-13 |
| 10-13 00:05 | (10-12, 10-13) | 10-13 |

Live DB, read-only, real `detect_gaps_1d_from_d1` for AAPL, SPY, MSFT, IONQ at now = 10-13 19:00, 22:00 and 10-14 01:30 UTC: no gap at 19:00 (session open), `(10-13, 10-14)` at 22:00 and 01:30, overlap end 10-14. A request window ending 10-14 00:00 is at or after the 10-13 close, so `daily_due_reason` no longer returns `not_current`; the name leaves the queue after the evening ask instead of being asked again after midnight. QRVO shows its genuine holes (no IBKR 1d raw), not a loop.

## Finding 2: first-bar read

`load_first_bars` is gone. Measured on 30 random active symbols: the old per-symbol MIN took 54.6 s for 10 symbols (the review saw more than 170 s for 30); the per-timeframe variant took 5.3 s for 30 symbols and six timeframes, of which the hypertable planning cost (over a thousand chunks, about 0.2 s per statement) dominates. That is still about 4 minutes for the whole queue, so the read is now lazy: `load_first_bar(conn, symbol, timeframe, vendor)` runs only inside `_head_floor`, only when no verified head exists, the window is not a tail and the timeframe needs more than one chunk, once per (vendor, symbol, timeframe) per run.

Startup path measured with the real fetcher classes (`--dry-run` flow plus `_default_context`, scratch script, 600 s timeout): queue read 0.3 s, `_default_context` loads 0.0 s (608 empty ranges, 703 verified heads, 2,355 floors), dry run total 0.6 s.

## Finding 3: seeded floors, per-timeframe heads, shut-out series

Migration 478 (applied with `psql -f`, committed in `0b8d3aa73`; no ALTER on `ohlcv_raw` or `ohlcv_revision`): adds `ohlcv_provider_head.head_kind` (`verified` or `floor`, CHECK), marks migration 465's seed rows (exact seed values and statement time) as `floor` (2,355 rows: 1,529 5m, 826 1d; 703 genuine 1d heads stay `verified`), and resets `consecutive_failures` for the ibkr 1d series whose failed or timed-out requests ended at or before the vendor's own first 1d raw bar. The reset follows the cause fix in the same commit and apply step.

Code: `load_fresh_heads` returns verified heads keyed (symbol, timeframe); `load_tape_floors` returns floors; `record_head` is replaced by the three-column upsert that makes the row verified (the old two-column upsert would have failed with 42P10 against the live primary key). `_head_floor` runs `get_head_timestamp` whenever no verified head exists for the series (one provider call per symbol per run, one head row written per timeframe), and uses a floor only as the fallback bound. A failed or timed-out window that ends at or before the known head or floor is not added to the item's failures.

Repaired (counter 0 after 478): BEPC, CHRD, CLBK, DTM, ELE, IONQ, LION, NB, RAL, VTS. Not touched: PSKY, QRVO, WBD (counter 6). They have no failed or timed-out 1d request in the ledger, so the seeded floor did not cause their exclusion and the cause is not identified; they need their own look. All ten repaired series keep `last_fetch_status = error`, so the queue still treats them as due and the next fetcher run (held) decides them.

## Finding 4: coverage ledger zeroing

`rebuild_from_stored_state` and `refresh_1d_bounds` now run a second statement that zeroes bounds and row count of a provider row with no raw row of its own (status, failure counter and last_fetched_at untouched). Live check, read-only: exactly one such row exists (QRVO 1d ibkr, 2,954 rows, Tradier-era). Run under the fetcher lock (holder `plan-191-06-fixes-coverage-zero`, released) as a scoped rebuild of QRVO for both providers: QRVO 1d ibkr is now 0 rows with null bounds, status error, counter 6 unchanged.

Deviation: I did not rerun the full rebuild. The previous one took 47 minutes of whole-table aggregation and the owner asked for bounded reads beside the reconcile backfill; the zeroing step needs no aggregation and the live scan found one orphan. Re-verification of 20 rows against direct `count(distinct timestamp)`, min and max over `ohlcv_raw` for the vendor: ibkr 5m ELV, CSCO, KO; alpaca 5m LYV, REMX, ELV, IONQ; ibkr 15m LYV, ELV, MAS, VRSN; ibkr 1h LYV, ELV, MAS, VRSN; ibkr 1d LYV, REMX, ELV, IONQ; and QRVO 1d ibkr (0 and 0). 20 of 20 match.

## Finding 5: 1h expected grid

`_rth_grid_slots` for 1h is the opening bar at the session open, then clock hours while before the close. Checked against stored AAPL stamps: 2026-07-14 13:30, 14:00 .. 19:00; 2026-01-14 14:30, 15:00 .. 20:00; 2025-11-28 (half day) 14:30 .. 17:00. The planner now ends a slot where its bar ends (`min(slot + interval, next slot)`) and treats touching slots as one window, so a missing opening bar asks 13:30 to 14:00 and answered-window coverage uses the real bar length. The auditor shares `plan_gaps` and `expected_grid_slots`, so the rule is the same there; its three tests, which encoded the :30 stamps, now use the real stamps.

Quantified read-only on 40 random ibkr 1h series, from each series' first stored bar to now, through the real `detect_gaps_from_record` with the series' own answered windows:

| | old grid | new grid |
|---|---|---|
| expected slots | 1,195,596 | 1,195,596 |
| expected slots found in stored raw | 169,342 (14%) | 1,189,396 (99.5%) |
| planned gap windows | 32,552 | 455 |
| planned gap days | 8,120 | 91 |

Cost: no one-time re-pull is incurred. The old grid would have asked about 8,100 calendar days for these 40 series (about 180,000 for all 888 series, extrapolated); the new grid asks the 91 days of real holes (about 2,000 extrapolated). The remaining 91 are interior holes, not grid error.

## Findings 7 and 8

Finding 7: `FetchContext` keeps empty ranges, verified heads, floors and first bars keyed (vendor, symbol, timeframe); `_default_context` loads them for each vendor in `plan.providers`; `record_head_per_tf`, `empty_history.reconcile` and `reconcile_empty_history` take `ctx.vendor`. The `_EMPTY_HISTORY_PROVIDER` constant is deleted. A test confirms another vendor's verified head never floors an item.

Finding 8: `DAILY_NOT_COVERAGE_KINDS = ("smart_adjusted",)` in `gap_plan.py` is the one definition. The planner, `_LATEST_OWN_1D_SQL` (currency read) and the coverage ledger's 1d count (refresh, rebuild and the zeroing test) all exclude it. Live check: all 1,529 ibkr 1d ledger rows already equal the trades-only count, latest and earliest, so no rebuild is needed.

## Finding 9

The 06 summary headline and the plan truth are corrected: the fetch process still reads `ohlcv_observation` through `split_detection.overlap_pairs` and the run-end daily stage; the truth is met after plans 08 and 10.

## Findings 6 and 10 (not done, by instruction)

Appended to todo 535 as open items 6 and 10 with a recommended placement of plan 191-08 for both (one planner pass over the 1d no_data rule and the intraday forming-slot rule, before the fetcher resumes).

## Verification

Touched-area suites pass: `tests/unit/scripts`, `tests/unit/bars`, `tests/unit/services/test_bar_auditor_gaps.py`, `tests/unit/test_ohlcv_coverage_rebuild.py`, the new migration contract test, and the coverage integration file against the test database (including a new zeroing test). Full `tests/unit` was run once at the end: no failures (two skips, both pre-existing). No file under `src/intelligence/research` or `statistics` changed, so `repro_frozen` was not required.

## Deviations and limits

- Full coverage rebuild not rerun (above); a scoped rebuild plus a live scan of all ledger rows stands in.
- PSKY, QRVO and WBD stay excluded (cause not identified).
- `record_head` (two-column key) was replaced rather than kept: against the live primary key it would have raised 42P10 on the first head lookup.
- Migration 478 was applied before its commit landed because the first commit attempt failed on an untracked test file; the commit followed seconds later (`0b8d3aa73`) and nothing ran in between (the fetcher is held).

## Held units

Window still open (`logs/raw_cutover_window.json`, opened 2026-10-13T19:00:40Z). All ten units are uncleared (`cleared_by` null for each) and none was resumed: indicagent-bar-reconciliation-audit.timer, indicagent-dividend-event-writer-yahoo.timer, indicagent-ibkr-history-fetcher.timer, indicagent-bar-aggregator.service, indicagent-bar-auditor.service, indicagent-bar-derivation.service, indicagent-bar-reconciliation-audit.service, indicagent-bar-writer.service, indicagent-dividend-event-writer@yahoo.service, indicagent-ibkr-history-fetcher.service. The fetcher stays held until plans 08 and 10. Migration 477 is still not applied (the owner applies it). `ops_raw_backfill.py`, `ohlcv_raw` and `ohlcv_revision` were not touched; `dashboard/package.json` and `/home/bg/dev/indicagent-186-26` were not touched.
