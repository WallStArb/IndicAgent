# 340 - Feature-compute backfill stalled for 8 symbols across 12 symbol/tf cells, multi-year gaps for 7 of them -- 2026-08-21 dismissal of 11/12 as "not real gaps" was wrong

**Filed:** 2026-08-21
**Source:** Split out of todos 259/296's closure -- found while verifying `backfill_status`
against actual `feature_vectors` row counts for the 2026-08-05/06 universe expansion.
**Corrected 2026-09-18** (manual corpus audit, cross-checked against live OHLCV/feature_vectors
row counts and `backfill_status` -- see table below): 11 of the 12 cells this todo originally
dismissed as "stale checkpoint desync, not real gaps" are, in fact, real, severe, multi-year
partial backfills that silently stopped. The original check only confirmed `feature_vectors`
had *some* rows for each symbol/tf -- it never compared that row count or max timestamp against
the actual OHLCV coverage, so a backfill that completed 40% of a symbol's history and then
crashed looked identical to a stale-but-complete checkpoint.

## What

12 `backfill_status` rows at the 4 real target timeframes (5m/15m/1h/1d) are `status='failed'`,
spanning 8 distinct symbols. Verified live against `market_data_ohlcv_tradeable` (what OHLCV
actually exists) and `feature_vectors` (what got computed):

| symbol | tf(s) failed | OHLCV bars (5m) | feature rows (5m) | feature history stops | gap |
|---|---|---|---|---|---|
| BIL | 5m, 15m, 1h, 1d | 330,954 | 165,500 | 2018-03-07 | ~8.5 yrs |
| VRP | 5m, 15m | 210,856 | 16,000 | 2015-11-20 | ~10.8 yrs |
| ENPH | 5m | 275,538 | 85,000 | 2016-11-28 | ~9.8 yrs |
| GLD | 5m | 395,996 | 295,500 | 2021-07-23 | ~5 yrs |
| NAD | 5m | 294,876 | 141,500 | 2018-04-05 | ~8.4 yrs |
| SHY | 5m | 177,958 | 7,500 | 2017-12-26 | ~8.7 yrs |
| STIP | 5m | 213,666 | 87,500 | 2020-01-09 | ~6.6 yrs |
| **IHF** | 5m | 224,881 | **0** | (never started) | full history |

The first 7 (11 of the 12 failed cells) all share `error_msg='value out of range: underflow'`.
**`IHF`/`5m` is the one cell with a genuinely different signature** -- zero rows at all (not a
partial/stalled backfill) and a distinct error, `"expected a positive input, got 0.0"`. `IHF`
has full data at `15m`/`1h`/`1d` -- only `5m` never started.

**Likely shared root cause for the 7 underflow cells:** a `real`-column write overflow, not a
compute crash on the first bar -- each of these got 40-90% of its history computed and written
before failing, consistent with a specific *value*, not a structural bug, tripping a range
check partway through. Matches the CLAUDE.md gotcha on `real`-column float32-range clamping
(`_clamp_to_real_range` in `_batch_utils.py`) -- plausible trigger: a near-zero-variance
instrument (BIL is a T-bill ETF, near-zero-volatility by construction; also flagged in todos
341/362 for a related degenerate-HMM-fit failure) producing an extreme z-score or log-return
value on a specific historical bar that overflows a `real` column on write, killing the whole
symbol/tf backfill run at that point. `IHF`'s distinct `"positive input"` error suggests a
separate root cause (a literal-zero `log()`/division input), not the same bug.

## Fix shape (not investigated yet)

**For the 7 underflow cells (BIL/VRP/ENPH/GLD/NAD/SHY/STIP):**
1. Re-run `backfill_feature_factory.py --compute-only --symbols <symbol> --workers 1` for one
   of these (BIL is the best first target -- already flagged for a related near-zero-variance
   failure mode in todos 341/362, so a shared root cause is directly testable) to get a clean
   traceback and find the exact bar/feature that overflows on write.
2. Confirm whether the write hits `bulk_update_by_key`'s `real`-column clamp path or fails
   further upstream (a numpy/pandas overflow before the DB write is even attempted).
3. Decide handling per the Renaissance data-retention principle (never drop data that could
   contain signal): clamp/epsilon-floor the specific feature calculation for degenerate-variance
   instruments vs. widen the column type vs. skip-and-log the specific bar -- don't silently
   truncate the backfill again.
4. Once fixed, re-run backfill for all 7 -- this is potentially 5-11 years of 5m feature history
   per symbol, a real gap in the corpus `ic_engine` trains against for these names.

**For IHF (distinct root cause, smaller blast radius -- single symbol/tf, zero rows):**
1. Find the specific bar(s) triggering this -- re-run `backfill_feature_factory.py --compute-only
   --symbols IHF` (with `--workers 1` for a clean traceback) or query `market_data_ohlcv_tradeable`
   directly for IHF/5m bars with `volume=0` or `close<=0`/`open<=0` around the failure window.
2. Locate the exact feature computation with an unguarded `log()`/division call that assumes a
   strictly-positive input (candidates: any volatility-ratio, log-return, or Wilder-RSI-style
   calc -- grep `math.log(` / `np.log(` in `src/intelligence/feature_factory.py` and
   `feature_cache.py` for calls not already guarded against zero).
3. Decide the correct handling -- skip that one bar (matches "never drop data that could contain
   signal" only if the bar itself is a genuine synthetic/flat-carry placeholder that
   `market_data_ohlcv_tradeable`'s `volume > 0` filter should have already excluded; if it slipped
   through that filter, the bug may be upstream of Feature Factory entirely) vs. guard the
   specific calculation with an epsilon floor.

**Before running any of the above:** the full-corpus `ic_engine` run in progress as of
2026-09-18 (todo 378's chain) is CPU/RAM-saturated (10 workers, ~19/24 cores, ~1GB free RAM) --
don't launch `backfill_feature_factory.py` concurrently; it risks OOM-killing one or both
multi-day jobs. Wait for that run to finish first.

## Where

- `services/backfill_feature_factory.py` -- `_compute_symbol_tf`, `FeatureFactory.compute_batch`
- `src/intelligence/feature_factory.py` / `src/intelligence/feature_cache.py` -- candidate
  unguarded `log()`/division call sites (IHF) and candidate degenerate-variance feature calcs
  (the other 7)
- `services/_batch_utils.py` -- `_clamp_to_real_range`, the `real`-column write-guard path
- `backfill_status` rows: all 12 listed in the table above, `symbol IN ('BIL','VRP','ENPH',
  'GLD','NAD','SHY','STIP','IHF')`
- Related: [341](341-bil-etha-ibit-zero-regime-labels.md), [362](362-bil-5m-zero-regime-volatility-labels.md)
  -- BIL's separate degenerate-HMM-fit failures, plausibly sharing the same near-zero-variance
  root cause as this todo's underflow cells
