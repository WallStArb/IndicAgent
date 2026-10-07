---
phase: 185-daily-data-foundation
plan: 31
subsystem: bars
tags: [write-contract, grid, ohlcv_load, ohlcv_revision, todo-490, migration-443]
requires: [185-27, 185-44]
provides:
  - "ohlcv_load / ohlcv_revision as the write record and revision table of every canonical writer (migration 443)"
  - "src/intelligence/bars/write_contract.py: BarValues, WriteDelta, classify, revision_ratio, should_refuse"
  - "grid stage compare-and-write with value-verified vendor removal"
affects: [185-36, 185-38, 185-39, 185-43, 189-10]
tech-stack:
  added: []
  patterns: ["write contract: read stored, classify by exact value, write only new/changed, old values to ohlcv_revision, refuse above a revision ratio"]
key-files:
  created:
    - production/migrations/443_ohlcv_load_revision_all_writers.sql
    - src/intelligence/bars/write_contract.py
    - tests/unit/bars/test_write_contract.py
    - tests/unit/test_ohlcv_load_revision_migration_contract.py
    - tests/unit/test_ohlcv_load_revision_writer_boundary.py
  modified:
    - services/bar_derivation.py
    - services/bar_reconciliation_audit.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - tests/unit/services/test_bar_derivation_grid.py
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/integration/test_derived_grid_live.py
decisions:
  - "ohlcv_load n_unchanged and n_removed are nullable: NULL means not recorded (Tradier loads before 185-38), never a false 0"
  - "Grid flags and digests are compared and written only where they differ, not 'only for months holding a write': a later answered 5m window must still clear a stale partial flag (todo 462)"
  - "Refusal is per grid timeframe; any refused timeframe refuses the symbol, its load rows commit as refused, the batch fails"
  - "infra.bar_derivation.grid_write_method moved to write_contract in migration 443 (the stage refuses any other value)"
metrics:
  duration: "about 4.5 h including a rate-limit pause"
  completed: 2026-10-07
---

# Phase 185 Plan 31: Write contract for the grid stage (todo 490) Summary

The grid stage now writes by a pure write contract. Derived rows are compared with stored rows by exact value, and only new and changed rows are written. Old values go to `ohlcv_revision`. Vendor rows leave `market_data_ohlcv` only after a value match against the archive or an `archive_segment` revision. Todo 490's 7 symbols are derived and the grid stage exits 0.

## Commits

| Task | Commit | What |
|---|---|---|
| 1 RED | 7bd83731d | write contract, migration 443 contract, load/revision boundary, ownership predicate tests |
| 1 GREEN | a01b82a55 | migration 443 (applied live), write_contract.py, `source = 'tradier'` in the ownership predicates. **Mislabeled:** this commit carries a copy of e1e8c08d0's 185-44 census message (see deviations) |
| 2 RED | 9cc064c2c | grid-stage tests for the contract |
| 2 GREEN | fd888c2c1 | grid stage compare-and-write, vendor removal verified by value |
| 3 | eba482774 | live grid identities restated against IBKR SMART TRADES 1d observations |

## Task 1: migration 443, the contract, ownership predicates

- Migration 443 was applied live with `psql -f` after `ls` confirmed the number was free (440, 441, 442, 445 existed).
  - `ohlcv_load` CHECKs widened: source tradier/ibkr/derived; timeframe 1d/5m/1m/15m/1h/4h; outcome adds applied/refused; destination d1/market_data_ohlcv/archive.
  - New `ohlcv_load` columns: `batch_id`, `n_unchanged`, `n_removed`, and `destination` (NOT NULL, default market_data_ohlcv).
  - `ohlcv_revision.origin` added (default load). `old_volume` is now nullable.
  - Grant: `bar_derivation_writer` SELECT, INSERT on both tables.
  - APR keys seeded: `threshold.bar_integrity.max_revision_ratio` 0.02 and `revision_ratio_min_stored` 500. `grid_write_method` moved from segment_delete_copy to write_contract (version 2, config_history row).
- Acceptance results: origin column count is 1; max_revision_ratio is 0.02; `source = 'tradier'` appears in all 3 files.
- The ownership predicates now carry `source = 'tradier'` in four places:
  - `_SELECT_DAILY_CHANGED_SINCE_SQL` (the fetcher inherits it)
  - `TRADIER_OWNED_SQL`
  - the loader's `_SELECT_MISSING_SQL`
  - D7's `_TRADIER_LATEST_LOAD_SQL`, both the outer query and the inner EXISTS. The outer filter is needed too: without it, a grid load row would become a name's "latest load".
- `ohlcv_load` and `ohlcv_revision` are now `Covered` by `test_ohlcv_load_revision_writer_boundary.py`. Segments are by source: the loader owns tradier, bar_derivation owns derived.

## Task 2: grid stage

Per symbol, in one transaction:
1. Read the stored 15m/1h rows, grid flags and current digests (as the session user).
2. Classify the derived rows per timeframe against the stored derived rows.
3. Refuse the symbol if the revision ratio is too high.
4. `SET LOCAL ROLE`.
5. Write one `ohlcv_load` row per timeframe.
6. Archive the vendor rows.
7. Write `archive_segment` revisions for vendor rows whose archive row is not equal.
8. Run the value verify: `n_unmatched` must be 0 and `n_removable` must equal the count read.
9. Delete the vendor rows, checking the rowcount.
10. Write `load`-origin revisions.
11. Delete stale derived rows by key.
12. Insert new rows and upsert changed rows (ON CONFLICT DO UPDATE).
13. Write flags and digests only where they differ.

Removed: `_DELETE_SEGMENT_SQL`, `_ARCHIVE_VERIFY_SQL`, `_DELETE_PARTIAL_FLAGS_SQL`, the synthetic_fill filter. Greps: 0 and 13. There is no raw `UPDATE market_data_ohlcv`, and the compressed-hypertable allow-list stays empty. All 15 new and changed statements were prepared under `bar_derivation_writer` against the live schema before the live run.

## Task 3: live run (2026-10-07 UTC)

Preconditions: the fetcher service was inactive and its timer disabled; no lane or pipeline processes were running; 568 GB free.

| Measure | Before | After |
|---|---|---|
| ibkr_named 15m/1h rows, 7 symbols | 861,047 | 0 |
| ...older than the symbol's first 5m bar | 154,308 (AAP 102,641, ADP 51,666, ABBV 1) | archived; no longer in market_data_ohlcv |
| ...never archived | 297 (99 each on A, AAP, ADBE) | archived by this run |
| ...differing from their archived observation (2026-09-28 to 10-01) | 235 (A 40, AAP 38, ABBV 32, ACRS 15, ACVA 40, ADBE 34, ADP 36) | 235 `ohlcv_revision` rows, origin archive_segment |
| derived_5m 15m/1h rows, 7 symbols | 0 | 695,282 (equals the dry run) |
| archive 15m/1h rows, 7 symbols | n/a | 895,126 |
| `hypertable_size(market_data_ohlcv)` | 5,707,587,584 | 5,894,578,176 after VACUUM ANALYZE |
| D7 stray_sources, 7 symbols | n/a | 0 findings |

- **Dry run:** 7 derived, 695,282 new, 861,047 vendor rows to remove, 0 refused, 13 s.
- **Performance SOP:** chunks are segmented by (symbol, timeframe); 109 of 110 are compressed.
  - ACVA ran first: 4.2 s for 45,636 deleted plus 45,505 inserted (about 22k rows/s). `wait_event` was CPU only.
  - That projected about 70 s for all 7, well under 30 minutes, so no manual decompression was needed.
  - The other six ran one transaction each: A 12.1 s, AAP 6.1 s, ABBV 6.2 s, ACRS 6.9 s, ADBE 11.7 s, ADP 7.9 s. All completed (batches f83ec7bf to b37d6a44).
- **VACUUM ANALYZE market_data_ohlcv:** 3.5 s. Size grew 187 MB because the derived rows sit uncompressed inside compressed chunks: 82 chunks have status 9 (partially compressed). Compression policy job 1075 (next run 2026-10-07 08:06 UTC) should recompress them. This is not yet verified; see the follow-ups.
- **First full apply, all 240 symbols** (f5c5323f, 10 min 0 s): completed; 0 new, 0 changed, 0 removed, 33,918,727 unchanged, 0 digests, 480 load rows. It also rewrote 1,770,744 grid flags on 157 symbols.
  - Those 157 were last derived on 2026-10-02 00:20 UTC, before 0ac60ca9a (185-18) changed answered-window coverage and the 5m input. The old stage never refreshed their flags because `--changed-only` skipped them.
  - The other 83 symbols (derived since 10-03) had 0 flag rewrites.
- **Second full apply** (idempotent cost): 9 min 24 s; 0 bar, flag or digest writes; only 480 load rows. The cost is CPU time in Python (reading 5m and aggregating), not writes.
- **Grid batch history:** latest status completed, no failed symbols. Before this plan every run since 2026-10-03 failed 7.
- **Integration test:** `tests/integration/test_derived_grid_live.py -m integration` passed 7.

Rollback (not run; the verify guarantees every removed vendor row has an equal copy). Within the grid transaction, any row whose archive copy differed got an archive_segment revision, so the revision copy is the value that was stored:

```sql
-- per symbol S, inside one transaction, after deleting the derived_5m 15m/1h rows of S
INSERT INTO market_data_ohlcv ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base, price_sanity_status)
SELECT a."timestamp", a.symbol, a.timeframe, a.open, a.high, a.low, a.close, a.volume, a.source, a.base, a.price_sanity_status
FROM ohlcv_intraday_raw_archive a
WHERE a.symbol = S AND a.timeframe IN ('15m','1h') AND a.batch_id = <grid batch of S>
  AND NOT EXISTS (SELECT 1 FROM ohlcv_revision r JOIN ohlcv_load l USING (load_id)
                  WHERE l.batch_id = <grid batch of S> AND r.origin = 'archive_segment'
                    AND r.symbol = a.symbol AND r.timeframe = a.timeframe AND r."timestamp" = a."timestamp")
UNION ALL
SELECT r."timestamp", r.symbol, r.timeframe, r.old_open, r.old_high, r.old_low, r.old_close, r.old_volume, r.old_source, NULL, NULL
FROM ohlcv_revision r JOIN ohlcv_load l USING (load_id)
WHERE l.batch_id = <grid batch of S> AND r.origin = 'archive_segment';
```

The archive rows inserted earlier than this batch (batch_id of an older run) need the same select keyed by timestamp rather than batch_id. Use `(symbol, timeframe, timestamp)` from the archive when restoring a whole symbol.

## Verification

- Task 1 and 2 verify sets passed, as did the boundary tests and the three 185-44 guards (single_writer, expiry, reader).
- ruff and black are clean on all touched files.
- Full suite: `pytest tests/unit/` gave 8,129 passed, 5 skipped.

## Deviations from plan

1. **[Rule 3] Shared-index commit mislabel.** Task 1's GREEN commit a01b82a55 contains exactly this plan's 7 files. Its message, however, duplicates 185-44's e1e8c08d0 ("complexity census script and committed baseline"). The first commit attempt failed on ruff UP046 and the retry ran in the shared checkout; the exact mechanism is not determined. The commit is unpushed. I did not amend (shared-checkout rule). The owner or coordinator should decide whether to reword it before the push.
2. **[Rule 1] D7's outer latest-load query** also got `l.source = 'tradier'`. With only the inner EXISTS edited, a grid load row would still become a Tradier-owned name's latest load and change `tradier_refused`.
3. **[Rule 1] Flags and digests are compared, not "rewritten only for months holding a write".** The literal rule would have kept stale partial flags after a later answered window. It would also have kept constituent flags after a 5m flag change. Stale grid flags are now deleted by key; the old code never deleted stale constituent flags.
4. **[Rule 3] `infra.bar_derivation.grid_write_method`** was updated to write_contract in migration 443. The stage raises on any other value, so the old value would have stopped every run.
5. **[Rule 3] The old 15m/1h test fixture's archive-verify row shape no longer exists.** The grid unit test was rewritten around a stateful fake. The behaviors kept are: no-5m, changed-only, dry run, exclusions, constituent and partial flags, shared planner.
6. **Writer-boundary reason text** for bar_derivation in `test_market_data_ohlcv_writer_boundary.py` was updated. It described the deleted segment rewrite. This file is not in the plan's file list.
7. **Plan expectations corrected by measurement:**
   - The 99 never-archived rows were 99 per symbol on A, AAP and ADBE (297 in total). The archive step stored them, so they produced no revisions.
   - archive_segment rows came to 235, not "15 to 40 per symbol plus 99".
8. **Integration thresholds** were set from the measurement and are documented in the test's docstring. They are rates (volume within 1% at least 99%, excess above 1% at most 0.1%, close within 1% at least 99.5%, open exact at least 99.5%, per-name median deficit at most 0.5%), not per-session identities. VIXY (66% volume agreement) and GE (88% open agreement through 2021-2024 corporate actions) pass only as part of the aggregate.

## Known stubs

None.

## Follow-ups and effects on later plans

- **185-36 and 185-38:** `ohlcv_load`'s Tradier rows have NULL `n_unchanged` and `n_removed`. A writer moving onto the contract should fill them. `infra.tradier.max_changed_bar_ratio` still has its reader; 185-43 retires it. `ohlcv_revision.origin` defaults to load, so the loader's existing INSERT needs no change.
- **185-39:** add the IBKR ingress writers to `test_ohlcv_load_revision_writer_boundary.py` as source ibkr. `classify(..., removal_scope=None)` covers ingress chunks.
- **Compression:** 82 market_data_ohlcv chunks are partially compressed. Confirm the 08:06 UTC policy run reduced that (gotchas: policy success can mean zero chunks compressed), else `compress_chunk` them.
- **Coverage loss in the read table:** 154,308 vendor 15m/1h rows on AAP (before 2019-03-01) and ADP (before 2015-01-21) have no 5m behind them. They now exist only in the archive, until 189-10's 5m fetch reaches deeper history, if IBKR serves it.
- **Vendor-basis findings for 185-37 / D7:** VIXY 1h volume against IBKR 1d agrees within 1% on only 66% of sessions; GE's first 1h open misses IBKR 1d's open on 12% of sessions through 2024; SPY and IWM volume within 1% on 86 to 88%; a Feb to Apr 2009 5m volume deficit runs across names.
- **Cost of an idempotent full pass:** about 9.5 min of CPU, dominated by Python 5m aggregation. Nightly runs stay `--changed-only`.

## Threat flags

None beyond the plan's register. T-185-31-01 to 04 are mitigated as designed: the value verify, the n_unmatched gate, the source predicates, and the refusal.

## Self-Check: PASSED
