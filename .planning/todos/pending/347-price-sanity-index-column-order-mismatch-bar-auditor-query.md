---
status: pending
priority: P2
filed: 2026-08-21
source: investigating todo 336's zero-scan index finding -- found while cross-referencing
  each flagged index's definition against its real code consumer
---

# `idx_market_data_ohlcv_price_sanity_unaudited`'s column order can't serve its own
# intended consumer's query -- likely explains both the 0-scan finding AND part of todo
# 155's ~4.1-year backlog-clear estimate

## Finding

`idx_market_data_ohlcv_price_sanity_unaudited` (501MB across 257 chunks, confirmed 0
scans corpus-wide, see todo 336) is defined as:

```sql
CREATE INDEX idx_market_data_ohlcv_price_sanity_unaudited
    ON market_data_ohlcv (symbol, timeframe, "timestamp")
    WHERE (price_sanity_status IS NULL);
```

Its only real consumer, `services/bar_auditor.py`'s `_PRICE_SANITY_CANDIDATES_SQL`
(lines 78-84), queries:

```sql
SELECT symbol, timeframe, timestamp
FROM market_data_ohlcv
WHERE price_sanity_status IS NULL
  AND volume > 0
ORDER BY timestamp
LIMIT $1
```

**The index's leading columns (`symbol`, `timeframe`) are useless to this query** -- the
query has no equality filter on either column, and orders by `timestamp` alone across the
whole table. A btree index shaped `(symbol, timeframe, timestamp)` can only serve an
`ORDER BY timestamp` efficiently when `symbol`/`timeframe` are pinned by an equality
predicate first; without that, Postgres has no way to use this index to satisfy the sort,
and falls back to scanning by some other path (likely the compressed hypertable's default
time-based access path) -- explaining the 0 scans directly, not "nobody uses this," but
"nobody *can* use this as built."

## Why this might matter beyond the wasted 501MB

Todo 155 measured `BarAuditor`'s live price-sanity audit at **7.55s per 500-row batch**
against the real 215.6M-row (at the time) backlog, projecting **~4.1 years** to clear at
the default cadence -- explicitly attributed partly to "Task 1's own empirically-verified
finding that UPDATEs against this table's compressed chunks... are far more expensive than
a read of the same rows suggests." That analysis didn't consider whether the *read* half
(`_PRICE_SANITY_CANDIDATES_SQL`'s own candidate-selection query) is itself index-served or
falling back to a slower path -- worth checking `EXPLAIN ANALYZE` on this query before
assuming the write side is the sole bottleneck todo 155 already diagnosed.

## Fix (not built, needs its own review before touching this hot table)

The index shape that would actually serve `_PRICE_SANITY_CANDIDATES_SQL` is closer to:

```sql
CREATE INDEX ... ON market_data_ohlcv (timestamp)
    WHERE price_sanity_status IS NULL AND volume > 0;
```

-- dropping `symbol`/`timeframe` entirely (the query never filters on them) and adding
`volume > 0` to the partial predicate (currently only `AND volume > 0` is a runtime filter,
not baked into the index condition, so it can't be pruned at the index level).

**Not built or deployed here.** This is `market_data_ohlcv` -- the same table class
(compressed hypertable) whose DDL/write-cost surprises already caused the 2026-08-13
768GB disk-full incident (`project_disk_full_incident_2026_08_13` memory) and the
performance-investigation SOP's own origin story (todos 149/161). Any index
add/drop here should follow `docs/foundation/performance-investigation-sop.md` (measure
first with `EXPLAIN ANALYZE`, check compression status, don't theorize) and land with
explicit review, not as a drive-by fix discovered mid-audit. Also needs the same
`compressed_hypertable_write_session`-style pause-compression-policy discipline
(CLAUDE.md's Compressed-hypertable column type changes note) if the fix touches DDL on
compressed chunks.

## Cross-refs

- [336](336-unused-index-cross-chunk-verification.md) -- filed this finding while
  verifying the original zero-scan-index audit
- [155](155-price-sanity-status-historical-backfill.md) -- the backlog-clear-time
  estimate this index mismatch may partly explain
