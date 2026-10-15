# Review of plan 191-10 (d0907003b..HEAD)

Read-only review; SELECT-only checks against the live DB on 2026-10-15.

## Findings (ranked)

1. MEDIUM - The d1-bootstrap stamp fix is code-only; stored rows keep the import clock.
   Evidence: `ohlcv_request` caller `d1-bootstrap` still has 2,793 requests with answered_at
   2026-09-30 10:12 to 19:59 (import clock, not the earliest possible answer). 7.71M current
   `ohlcv_raw` 1d rows point at them. 212 keys on 80 names currently hold the bootstrap value
   although `ohlcv_revision` (origin raw) holds an earlier real serve with a different close;
   in all 212 the displaced serve was answered before the bootstrap stamp. Last-wins therefore
   chose the corpus value by import clock, the exact defect e9e96b2f9 fixes for new imports.
   Split detection (`pair_answers`) and dividend pairing order by these stamps.
   Fix: one logged migration or ops step re-stamping d1-bootstrap requests (and raw.served_at
   where set) to the midnight after each request's last bar, then re-resolve the 212 keys by
   serve time (value flips back to the real serve, displaced value to revision). Do before the
   split and dividend consumers are cleared.

2. LOW/MEDIUM - `pair_d1_series` docstring says superseded offers never pair, but
   `own_trades` (via `_run_values`) and `adj` keep a run's `origin = 'superseded'` row when it
   is the only answer for that date. Such a value was never stored. The adjusted side and the
   own-TRADES side can then pair a never-stored value. Loud failure is not guaranteed.
   Fix: drop `origin == 'superseded'` rows from `own_trades`, or state that the run's offered
   value is the intended pair and fix the docstring. Also `_run_values` depends on row order
   (UNION ALL, no ORDER BY): a superseded row seen first with a different close than the
   current row raises instead of being skipped. Add `ORDER BY current DESC` or sort in Python.

3. LOW - Alpaca guard: bounds the stamp only against the newest bar (after it, within 120 h).
   A re-stamped or copied old artifact whose newest bar is under 120 h old still passes, and
   every older bar in it inherits that stamp. Stamp is plain parquet metadata, so it is a
   mistake guard, not tamper-proof. Acceptable; tighten only if artifacts are ever copied.

## Checked, no defect found

- Dividend deviation 4 (D-191-D refined): the pairing takes the latest TRADES answer, current
  or displaced, served no later than the adjusted serve; a post-serve restatement never pairs
  (its displaced earlier value does), so a real restatement is not hidden and no lookahead
  enters. A split re-scale of TRADES between the two serves appears as a revision inside that
  window and is picked up as the latest. Missing dates still reach `join_adjustment_pairs`,
  which refuses inside the overlap.
- Split detection: earlier answers are filtered to other runs and `answered_at` before the
  fresh one, complete sessions only, so no future revision is read. Unchanged re-serve gives
  ratio 1 by construction. Names with no changed value are skipped; the changed-name test
  covers both raw-at-run and displaced-by-later-run.
- Listing venue, bar_hold: vendor/kind mapping and `venue_<route>` kinds consistent with
  migration 476; the legacy-import row is excluded from route evidence in bar_hold.
- 4h delete (488): guarded by exact counts, all 2,184 raw values logged to `ohlcv_revision`
  under two `dq-delete-191-10` loads (verified 2,184 rows), canonical equality checked in the
  migration, balance assertion before COMMIT. Live: 0 raw 4h rows left. feature_vectors and
  market_regimes have no `timeframe` column of that name, so I could not confirm derived 4h
  rows by that route; `bar_source_policy` closed. Confirm derived tables hold no 4h rows.
- Compression (486/489): 336 of 339 chunks compressed, policy job 1076 at 60 days. Per-symbol
  `ohlcv_raw` read plans use the segment keys (AAPL 1d: 40 ms execution, 367 ms planning from
  339 chunks; revision lookup 17 ms). Planning cost is the only cost; fine for per-name reads,
  watch it in a 1,500-name loop.

## Verdict

Fetcher resume is safe from the 191-10 code paths: nothing here writes bars, and the Alpaca
guard, 4h delete and compression hold. Resume order stays: clear the reserve list first, then
the selection gate must exit 0 before the fetcher. Finding 1 does not block the fetcher (new
serves post-date 09-30 and win) but should be repaired before the split and dividend units are
cleared, since both order answers by these stamps.
