# 336 - Verify whether flagged zero-scan indexes are actually unused before considering a drop

**Filed:** 2026-08-20
**Source:** `/supabase:supabase-postgres-best-practices` read-only DB audit, run while `ic_engine.py`
was mid-run on the corpus pipeline (step 5/8, ~162/231 symbols).

## Finding

A `pg_stat_user_indexes` query against per-chunk stats surfaced several indexes with `idx_scan = 0`
on their largest chunk, sized large enough to be worth reclaiming if genuinely dead:

- `idx_market_data_ohlcv_price_sanity_unaudited` -- ~500MB combined across 2 chunks
  (`_hyper_30_63932_chunk` 387MB, `_hyper_30_73682_chunk` 110MB)
- `feature_ic_scores_history_cell_idx` -- 808MB (`_hyper_103_73684_chunk`)
- `idx_market_data_ohlcv_base` -- ~116MB combined across 2 chunks
- `feature_ic_scores_history_archived_at_id` -- 43MB
- `ensemble_alpha_symbol_tf_idx` -- 15MB

**Not conclusive as-is.** TimescaleDB tracks `idx_scan` per chunk, not aggregated per logical
hypertable index -- a single chunk reading 0 doesn't mean the index is unused overall, especially
for indexes that might only get hit by queries scoped to older/different chunks, or by planner
choices that vary chunk-to-chunk. Before considering dropping any of these:

1. Aggregate `idx_scan` across **all** chunks for each of these index names, not just the one
   chunk sampled here.
2. Check `pg_stat_user_indexes` reset history (`pg_stat_reset` calls) -- a recent stats reset
   would make `idx_scan=0` meaningless regardless of real usage.
3. Grep `src/`/`services/` for query patterns that would use each index's columns, to sanity-check
   against the stats before trusting them alone (an index can be structurally necessary for a
   rarely-hit code path stats haven't captured yet).

## Why this isn't urgent

None of this blocks or was prompted by an active problem -- DB health check came back clean
overall (connections 6/200, no seq-scan-dominated large tables, only `market_regimes` showing
mild dead-tuple bloat at 11.2%, all 5 uncompressed hypertables trivially small). This is a
"worth a look sometime" cleanup candidate, not corruption or performance degradation.
