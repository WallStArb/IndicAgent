---
created: 2026-02-24T20:52:53.602Z
updated: 2026-03-28T00:00:00.000Z
title: Add keyset pagination to features export and REST endpoint
area: api
priority: 19
tier: feature
files:
  - src/api/routes/features.py:60-189
---

## Problem

Two issues with the current pagination model:

1. **REST endpoint** (`GET /features/{symbol}/{tf}`) uses `ORDER BY ts DESC LIMIT N` with no cursor. You cannot reliably paginate through history — repeated calls with the same limit always return the same top-N rows.

2. **Parquet export** caps at 100K rows with no pagination at all. With 23 symbols × 4 TFs × 35 days × 1440 1m bars ≈ 4.6M total rows, only ~2% of the dataset is reachable in one export call. ML training workflows need access to the full dataset.

## Solution

- **REST endpoint**: Add optional `before_ts` query param for keyset pagination. `AND ts < $before_ts` gives stable, index-friendly pagination without OFFSET.
- **Parquet export**: Add chunked export — either multiple pages via `before_ts` cursor, or a streaming response that writes Parquet row groups incrementally. Raise or remove the 100K cap once pagination is in place.
