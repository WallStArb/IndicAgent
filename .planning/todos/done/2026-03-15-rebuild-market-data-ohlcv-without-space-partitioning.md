---
created: 2026-03-15T20:44:48.355Z
title: Rebuild market_data_ohlcv without space partitioning
area: database
files:
  - production/docker-compose.yml
  - production/scripts/historical_backfill.py
---

## Problem

`market_data_ohlcv` has **15,721 chunks at ~35 kB each** due to space partitioning (8 partitions by symbol) combined with 1-day time intervals. TimescaleDB recommends 25–100 MB/chunk — current setup is ~700× too small.

Root cause: the hypertable was created with both a time dimension (1-day intervals) AND a space partition (8 partitions by `symbol`). With 60 instruments across multiple timeframes and 7yr of data, this causes chunk explosion.

Impact:
- Any aggregate or GROUP BY query on `market_data_ohlcv` takes 4–5 seconds (planner evaluates 15k chunk metadata)
- `DISTINCT symbol` scans all chunks (~19s observed)
- `pipeline_reset.py` row count uses `reltuples` estimate to avoid this, but any new diagnostic query risks hitting it

Note: `market_data_ohlcv` is cold storage only — never written by the live pipeline. Only `historical_backfill.py` writes to it.

## Solution

Recreate the hypertable with time-only chunking at a wider interval:

```sql
CREATE TABLE market_data_ohlcv_new (LIKE market_data_ohlcv INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
SELECT create_hypertable('market_data_ohlcv_new', 'timestamp', chunk_time_interval => INTERVAL '7 days');
-- Copy data in batches by symbol+timeframe
-- Rename: DROP market_data_ohlcv, ALTER market_data_ohlcv_new RENAME TO market_data_ohlcv
-- Re-add indexes, compression policy
```

Expected result: ~365 chunks (7yr / 7 days) vs current 15,721 — aggregate queries drop from 5s → sub-100ms.

Batched copy needed given 1.3 GB volume. Run during off-hours; `historical_backfill.py` must be paused.
