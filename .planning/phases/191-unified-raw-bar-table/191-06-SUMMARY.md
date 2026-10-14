WINDOW STILL OPEN, fetcher stopped, fetcher NOT ready to resume (plans 08 and 10 still owed). Held units (all inactive or failed, none cleared, none resumed): indicagent-bar-reconciliation-audit.timer, indicagent-dividend-event-writer-yahoo.timer, indicagent-ibkr-history-fetcher.timer, indicagent-bar-aggregator.service, indicagent-bar-auditor.service, indicagent-bar-derivation.service, indicagent-bar-reconciliation-audit.service, indicagent-bar-writer.service, indicagent-dividend-event-writer@yahoo.service, indicagent-ibkr-history-fetcher.service. Record: `logs/raw_cutover_window.json` (opened 2026-10-13T19:00:40Z); `ops_raw_cutover_window status` at the end of this plan shows `cleared_by=None` for all ten.

---
phase: 191-unified-raw-bar-table
plan: 06
subsystem: bar data layer
tags: [ohlcv_raw, gap-planner, coverage-ledger, per-source, empty-history]
requires: [191-05]
provides:
  - one vendor-scoped answered-window SQL and vendor-scoped stored-slot reads over ohlcv_raw (`_d1_gaps.py`)
  - verification asks (overlap, 1d session overlap, escalation refetch) separated from the gap planner (`_with_verification_asks`)
  - ohlcv_coverage rebuilt from raw per provider (ibkr and alpaca), one `raw` destination
  - per-vendor empty-history probes and 1d currency read
affects: [191-07, 191-08, 191-10, 191-11, 191-16]
key-decisions:
  - the fetch question is per source (D-191-K in the design doc)
  - overlap and refetch asks are kept, outside the planner, because split detection and the 5m waiver read them
  - no migration (ohlcv_coverage has no destination column)
requirements-completed: []
metrics:
  tasks: 2
  completed: 2026-10-14
---

# Phase 191 Plan 06: fetcher-side readers onto ohlcv_raw, per source Summary

The gap planner, the answered-window and existence reads, the empty-history probes, the queue's 1d currency read and the coverage ledger now read the asking vendor's own `ohlcv_raw` rows and requests. Nothing in the fetch process reads `ohlcv_observation` or `ohlcv_intraday_raw_archive`, and another vendor's rows, answers or the canonical selection never cover a slot.

Code commit: `886e9c212` (one commit for both tasks: the item module wires the planner and the coverage destination together, so splitting them leaves a commit that does not import). This summary follows in its own commit.

## What was done

Task 1, coverage ledger over raw.
- `services/ohlcv_coverage_writer.py`: `DESTINATION_ARCHIVE`, `DESTINATION_GRID` and `DESTINATION_TABLES` are replaced by `DESTINATION_RAW`; `CoverageDelta` keeps its fields and rejects any other destination. `_REBUILD_SQL` aggregates `ohlcv_raw WHERE vendor = provider` (min, max, `count(DISTINCT timestamp)`), and `refresh_1d_bounds` does the same for 1d. `rebuild_from_stored_state(cur, symbols, provider=None)` rebuilds every provider in `REBUILD_PROVIDERS` (ibkr, alpaca; the Alpaca filter is now written because its leaf exists); an unknown provider raises before any SQL. `existing_timestamps` had no caller and is deleted instead of repointed.
- `_intraday_persist._upsert_coverage` no longer counts tradeable rows only; `bar_load` builds its delta with the raw destination and provider alpaca; `_ChunkPersister` labels the delta with the context's vendor.
- No migration: `ohlcv_coverage` has no destination column or CHECK (a test reads migrations 432, 464 and 465 to pin that), so the Files list entry for `NNN_ohlcv_coverage_raw_destination.sql` is dropped.
- `bar_reconciliation_audit.coverage_cache_drift` keyed ledger rows by (symbol, timeframe); with an ibkr and an alpaca row on one series the rows overwrote each other. It is now keyed by provider.

Task 2, gap planner and existence reads.
- `_d1_gaps.py`: one `_ANSWERED_WINDOWS_SQL` serves 5m, 15m, 1h and 1d (todo 527 item 1 inside this file), filtered by `ohlcv_request.source = vendor` and corroborated by a raw row of the same vendor in the window. Stored slots come from `ohlcv_raw` with `vendor = %s` for intraday; 1d reads the vendor's raw rows of every kind except `smart_adjusted` (kind rules of D-191-A; the plan's `smart_trades` plus `venue_%` list is the same set today for IBKR, and the exclusion form needs no edit for a second vendor). A 1d bar counts only if `session_complete_at(bar_date, served_at, sessions)` (D-191-J); a row with no `served_at` counts. The old "bar_date < today" rule is gone: a complete bar served after the close covers its session, a bar served mid-session does not, and an unfinished session is never asked for or accepted as a complete answer. `session_complete_at` takes an optional prebuilt session map so a full-depth read does not call the calendar once per row.
- `_history_fetch.detect_gaps` (the 1m and 4h fallback, the plan's "lines 843-855" slot-existence check) reads `ohlcv_raw` by vendor.
- `_history_fetch_item._plan_gaps(ctx, instrument, timeframe, start_dt)` is the pure per-source question. `FetchContext.vendor` is the item plan's provider name (ibkr when no plan). The `_VENDOR_PARITY_TFS` coverage and overlap exceptions are deleted.
- `_empty_history.py` (not in the plan's list, same principle): `has_bar_before`, `has_bar_between` and `load_first_bars` read the provider's own raw, and the confirmed-span and candidate requests are filtered by `source`. With the canonical view a bar from another vendor made an IBKR pre-history window look like "not pre-history", so the confirmed empty was never recorded and the walk repeated each run.
- `_fetch_queue._LATEST_OWN_1D_SQL` replaces the canonical 1d currency read (the provider's own latest 1d raw bar).

## Overlap and refetch lanes: kept, outside the planner

Owner direction was to delete `with_overlap_window`, the overlap window and the refetch escalation unless a reader still needs them. Readers exist, so they stay, but they are no longer part of `_plan_gaps`; they live in `_with_verification_asks`, with a test that the planner signature has no overlap or refetch parameter. Reason: a restated history (a split, a rescaled level) is visible only when stored slots are asked again and the fresh serve is compared with the same source's stored values. Readers: the update lane's 5m overlap judgment (`overlap_pairs`, `judge_overlap`), the 1d session overlap that makes a split show as a constant ratio (D-21, `split_detection.overlap_pairs`), the escalation refetch through the waiver (`_escalate`, `_WAIVER_SQL`), and `ops_split_detect`'s `--overlap-sessions` refetch. Deleting them leaves no restatement ever observed and the waiver never fires (amendment to this plan). Recorded as D-191-K.

## Verification against the live database (read-only, bounded)

Every new predicate was run against `indicagent` with a read-only session and a statement timeout, so a stale predicate cannot silently return zero rows:
- Raw kinds present for the 1d predicate: ibkr `smart_trades`, `smart_adjusted`, `venue_amex/arca/bats/island/nyse`; tradier `consolidated`. AAPL: 5,172 ibkr smart_trades rows against 5,195 observation rows (route <> TRADIER).
- MSFT 1d: 5,073 observation sessions, 5,073 raw sessions (kind <> smart_adjusted), zero only-in-observation, zero only-in-raw.
- 60 random compute-eligible symbols, full 1d depth from 2016: the old observation-based plan and the new raw-based plan are identical for all 60 (11,278 windows each).
- 15m and 1h: old archive-based plan equals the new raw-based plan for AAPL 1h and 15m, SPY 1h, MSFT 15m, BEPC 1h (symmetric difference of archive and raw ibkr stamps for AAPL 1h since 2024 is zero).
- 1d raw rows since 2026-09-01 (47,752): none with NULL `served_at`, none served before their stamp, so the completeness filter changes nothing today.
- Answered windows and stored slots returned rows for every sampled series (the planner outputs below are non-trivial).

Planner dry run (the fetcher's `--dry-run` only prints the ranked queue, so a read-only harness calls `_plan_gaps` for 5 names x 1d, 5m, 15m): `logs/planner_before_20261014T040029Z.json` and `logs/planner_after_20261014T040928Z.json`.

| Series | Before | After | Reason |
|---|---|---|---|
| 1d, five names | 1 window each | identical | the one open session is 2026-10-13, complete, not yet asked (fetcher held) |
| 15m, five names | 9, 11, 6, 94, 94 | identical | archive equals raw |
| AAPL 5m | 3 | 3, last tail window starts 2026-10-09 14:15 (was 16:15) | IBKR's own raw ends 14:10; canonical had Alpaca rows to 16:10 |
| SPY 5m | 3 | 3, tail starts 14:15 (was 20:00) | same |
| MSFT 5m | 103 | 104 | one slot (2026-08-06 16:55) Alpaca holds and IBKR raw lacks |
| BEPC 5m | 186 | 94 | IBKR holds no 5m raw for BEPC; the old plan asked only the extended-hours slots Alpaca lacked, the new one asks each whole session once |
| LION 5m | 190 | 94 | same |

The plan expected differences only where the old planner "ignored loser rows". The actual differences go the other way: the old plan was hidden by another vendor's canonical rows and the new plan asks what IBKR itself lacks. No 1d session already answered by IBKR is requested.

Unit and integration:
- `tests/unit/` full run: exit 0 (two pre-existing skips), run after the code change (a later docstring-only edit was followed by the touched-area suites).
- `tests/integration/test_ohlcv_coverage_atomic_write.py` (8 passed) and `test_ingress_write_contract.py` (one skip: no compressible chunk on the test database).
- Greps from the plan: `grep -rnE "(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)" scripts/infrastructure services/ohlcv_coverage_writer.py services/bar_load.py` is empty; the coverage writer mentions neither old store. No file under `src/intelligence/research` or `statistics` changed, so `repro_frozen` is not required.
- ruff and black clean on touched files. mypy on `_d1_gaps.py`: two arg-type errors in lines that predate this plan (`Sequence` against `list`, `EmptyRange | None`).

## Coverage ledger rebuild and 20-row comparison

The rebuild ran with the window open under the fetcher lock (holder `plan-191-06-coverage-rebuild`, released), in batches of 25 symbols through a scratch script that calls `rebuild_from_stored_state` (the fetcher's `--rebuild-coverage` is one transaction over all symbols, too heavy beside the balance checks). 1,551 symbols, 5,346 rows written, 47 minutes. A scoped pass over the first 20 symbols ran before it.

Result by provider and timeframe, rows / sum of row_count: alpaca 5m 1,529 / 302,089,665; ibkr 5m 465 / 89,128,760; ibkr 15m 887 / 94,025,277; ibkr 1h 888 / 25,385,758; ibkr 1m 233 / 9,775,958; ibkr 4h 2 / 2,184; ibkr 1d 1,529 / 4,577,061.

20 sampled rows (seeded), ledger against `select count(*), count(distinct timestamp), min, max from ohlcv_raw where symbol, timeframe, vendor`: 20 of 20 match on count of distinct slots, earliest and latest.

| Series | Ledger count | Raw count(*) / distinct | Match |
|---|---|---|---|
| CMS 15m ibkr | 129,519 | 129,519 / 129,519 | yes |
| EME 5m alpaca | 209,246 | 209,246 / 209,246 | yes |
| EVER 1d ibkr | 28 | 28 / 28 | yes |
| EXEL 15m ibkr | 131,199 | 131,199 / 131,199 | yes |
| IT 1d ibkr | 5,037 | 10,062 / 5,037 | yes (smart_trades and smart_adjusted share stamps) |
| JBHT 1d ibkr | 5,073 | 10,099 / 5,073 | yes (same) |
| LHX 1h ibkr | 35,062 | 35,062 / 35,062 | yes |
| LXP 5m alpaca | 214,531 | 214,531 / 214,531 | yes |
| MDLN 1d ibkr | 205 | 205 / 205 | yes |
| MSI 15m ibkr | 130,171 | 130,171 / 130,171 | yes |
| MTN 5m alpaca | 211,008 | 211,008 / 211,008 | yes |
| PH 5m alpaca | 215,643 | 215,643 / 215,643 | yes |
| POR 1d ibkr | 69 | 69 / 69 | yes |
| RCMT 1d ibkr | 5,124 | 10,148 / 5,124 | yes (same) |
| RSPH 1d ibkr | 4,960 | 9,912 / 4,960 | yes (same) |
| TOL 5m alpaca | 227,301 | 227,301 / 227,301 | yes |
| TPR 5m alpaca | 226,801 | 226,801 / 226,801 | yes |
| VIXM 5m alpaca | 117,480 | 117,480 / 117,480 | yes |
| WYNN 15m ibkr | 130,200 | 130,200 / 130,200 | yes |
| XTL 5m alpaca | 39,303 | 39,303 / 39,303 | yes |

Behavior change, as the design doc's Problem section intends: the IBKR 5m ledger now counts every IBKR raw row, including slots where Alpaca is canonical (about 84.4M before, 89.1M after), the Alpaca 5m ledger counts zero-volume extended-hours rows the old tradeable count skipped (222M before, 302M after), and the IBKR 1d ledger describes IBKR's own history (earliest from IBKR's first answer), not the Tradier-era canonical depth (7.0M before, 4.6M after). The queue's proven-depth and staleness reads therefore see IBKR's own coverage.

## Deviations from plan

1. [Rule 3] One code commit instead of one per task; the two tasks meet in `_history_fetch_item.py`.
2. [Rule 2] Files beyond the plan's list, same principle (per-source reads): `_empty_history.py`, `_fetch_queue.py` (one SQL), `ohlcv_history_fetcher.py` (`load_first_bars` call), `services/bar_reconciliation_audit.py` (provider key), `src/intelligence/bars/sessions.py` (optional session map), design doc D-191-K, todo 527 progress note.
3. [Rule 1] `tests/integration/test_ingress_write_contract.py` expected 100 pending rows after two refused offers; commit `64c004f63` (review finding 7) dedupes them to 50, so the test was already stale. Corrected.
4. [Rule 3] The plan's "find the fetcher's read-only planner dry run flag" has no such flag; a scratch harness (`planner_dump.py`, not committed) produced the before and after files.
5. [Rule 3] `/simplify` and `/review` are not invocable from this executor. I reviewed the diff myself (stale comments, dead `existing_timestamps` and `_VENDOR_PARITY_TFS`, the audit key collision); there was no independent review pass.
6. Overlap and refetch lanes kept (above).
7. `_STORED_SLOTS_SQL` per-table dict and the five answered-window copies in this module are gone; the copies in `bar_derivation`, `bar_reconciliation_audit` and `bar_auditor` remain (services cannot import from scripts; todo 527 note).
8. STATE.md, ROADMAP.md and REQUIREMENTS.md are not advanced: plan 04 is still open and the coordinator owns that bookkeeping on this shared checkout.

## Unresolved

1. The fetcher must stay held: split detection (`overlap_pairs`, the waiver) and the run-end daily stage still read `ohlcv_observation` (plans 08 and 10), and plan 07's Alpaca policy spans are not seeded. The resume guard needs summaries for 06, 08 and 10; this file satisfies the 06 part only.
2. Migration 477 is still not applied to the live database (as instructed). The four balance-check shards have since finished and written reports (`logs/raw_backfill_balance_20261014T034015Z.json`, `...T040015Z.json`, `...T042728Z.json`, `...T044254Z.json`); each has `exit_code` 1 and `unexplained` of 52,556, 47,308, 38,101 and 43,531. I did not analyze them; they belong to the plan 04 open item. They were already finished when I read them, so the rebuild above ran partly alongside them.
3. The 1h expected slot grid in `gap_plan.expected_grid_slots` stamps `:30` while IBKR 1h rows after the 14:30 partial bar are stamped `:00` in winter. AAPL 1h since 2024 plans 658 one-day windows, identically before and after this plan (old archive plan equals new raw plan). Not changed here; it will be re-asked each run until the grid rule or the answered windows cover it.
4. Column comments on `ohlcv_coverage` (migration 432) still describe the archive and grid destinations. Fixing needs `COMMENT ON` DDL; left for plan 16 or 17.
5. `infrastructure_ibkr_chunk_and_rate_limit_probe.py` reads `market_data_ohlcv` for its "instrument has no data" probe. A probe tool, not the fetch path, untouched.
6. Alpaca coverage rows keep their stored `last_fetch_status` (the Alpaca loader writes no `ohlcv_request` rows), as before.

## Known stubs

None.

## Self-Check: PASSED

Commit `886e9c212` is in `git log`; `tests/unit/test_ohlcv_coverage_rebuild.py`, `services/ohlcv_coverage_writer.py` and `scripts/infrastructure/backfill/_d1_gaps.py` exist; `logs/planner_before_20261014T040029Z.json` and `logs/planner_after_20261014T040928Z.json` exist; the ten held units show `cleared_by=None` and none is active.
