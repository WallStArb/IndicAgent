# 340 - IHF/5m feature compute: zero rows, "expected a positive input, got 0.0"

**Filed:** 2026-08-21
**Source:** Split out of todos 259/296's closure -- found while verifying `backfill_status`
against actual `feature_vectors` row counts for the 2026-08-05/06 universe expansion.

## What

Of the entire 231-symbol universe, only 12 `backfill_status` rows (at the 4 real target
timeframes 5m/15m/1h/1d) are not `status='complete'`. 11 of those 12 are stale checkpoint desync
(real `feature_vectors` data already exists despite the stale `'failed'`/non-complete status,
same class as todo 316/317) -- not real gaps.

**`IHF`/`5m` is the one exception: genuinely zero `feature_vectors` rows.** `IHF` has full data
at `15m` (108,700 rows), `1h` (34,769 rows), and `1d` (4,776 rows) -- only `5m` is empty.
`backfill_status.error_msg` for this cell: `"expected a positive input, got 0.0"` -- distinct
from the other 11 failed cells' `"value out of range: underflow"` error, suggesting a different
root cause (likely a `log()`/division call somewhere in `FeatureFactory.compute_batch` hitting a
literal zero -- zero volume or zero price on a specific 5m bar for this symbol, IHF being a
thinner-traded sector ETF).

## Fix shape (not investigated yet)

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

## Where

- `services/backfill_feature_factory.py` -- `_compute_symbol_tf`, `FeatureFactory.compute_batch`
- `src/intelligence/feature_factory.py` / `src/intelligence/feature_cache.py` -- candidate
  unguarded `log()`/division call sites
- `backfill_status` row: `symbol='IHF', tf='5m', status='failed'`,
  `error_msg='expected a positive input, got 0.0'`, `started_at='2026-08-12 19:18:53 UTC'`
