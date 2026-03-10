---
created: 2026-03-04T00:00:00.000Z
title: Add gap-fill service for market_data_ohlcv
area: database
files:
  - production/scripts/historical_backfill.py
  - src/providers/ibkr.py
---

## Problem

TWS disconnects and service downtime leave gaps in `market_data_ohlcv`. The existing `historical_backfill.py` refetches entire date ranges but is not gap-aware — running it wastes time re-fetching data that already exists. No automated mechanism detects and fills specific missing windows.

## Solution

A gap-aware script (or service) that:
1. Queries `market_data_ohlcv` for each symbol/TF to find contiguous gaps (missing 1m bars where there should be data during RTH)
2. Fetches only the missing windows from IBKR (targeted `reqHistoricalData` calls)
3. Runs Stage 2 replay for those windows to backfill `intelligence_features`

Distinct from full historical backfill — this is a lightweight maintenance job, suitable for a daily cron or manual trigger after service downtime.
