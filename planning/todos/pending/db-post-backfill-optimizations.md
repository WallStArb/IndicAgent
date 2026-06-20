# DB Post-Backfill Optimizations

**Created:** 2026-06-20  
**Trigger:** After ETF backfill completes (run_historical_pipeline PID 455410)

## Actions

### 1. Compress new market_data_ohlcv chunks
The backfill creates new/partially-compressed chunks outside the 30-day auto-compression window.

```sql
SELECT compress_chunk(c, if_not_compressed => true)
FROM show_chunks('market_data_ohlcv', older_than => INTERVAL '30 days') c;
```

### 2. Vacuum market_data_gaps
Backfill writes and resolves many gap rows — dead tuples accumulate during the run.

```sql
VACUUM ANALYZE market_data_gaps;
```

### 3. Analyze market_data_ohlcv
Planner stats will be stale after loading years of historical data across 55 symbols.

```sql
ANALYZE market_data_ohlcv;
```

## Already Done
- `VACUUM ANALYZE market_data_gaps` run 2026-06-20 mid-backfill (cleared 321 dead tuples)
- Confirmed compression enabled on both hypertables; segmentby `{symbol, timeframe}` orderby `{timestamp}` — optimal for access patterns
- No missing FK indexes
- Partial indexes already well-used across all signal tables

## Not Worth Doing
- GIN indexes on JSONB columns — access pattern is key extraction (`->>'key'`), not containment; no benefit
- PK column-order flip on intelligence_features/market_data_ohlcv — secondary indexes are 8KB (data in compressed chunks); not impactful at current scale
