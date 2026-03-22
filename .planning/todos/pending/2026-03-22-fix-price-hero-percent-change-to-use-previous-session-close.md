---
created: 2026-03-22T23:40:06.101Z
title: Fix price-hero percent change to use previous session close
area: ui
files:
  - dashboard/src/components/price-hero.tsx:99-103
  - dashboard/src/lib/types.ts:376
  - dashboard/src/hooks/use-market-stream.ts:431-466
  - src/api/routes/market_data.py
---

## Problem

`price-hero.tsx` computes `%change` against `session.open` (the 6pm ET open) instead of the previous session's official close. This is misleading — the standard convention is change-from-close.

The plumbing is mostly there: `prevClose` exists in `SymbolData` (types.ts:376), and the dashboard already calls `/api/market-data/session?symbols=...` on mount to populate it — but that endpoint returns 404 (never implemented).

## Solution

1. Add `/api/market-data/session` endpoint to `market_data.py` — for each symbol, query the last `1d` bar from `market_data_ohlcv`. Using the daily bar avoids per-asset-class close-time logic (ES closes 4:15 ET, equity 4:00 ET, crypto rolling) since IBKR bakes the correct session boundary into the bar naturally.

2. Change `price-hero.tsx` lines 99-103 to use `data.prevClose` instead of `session.open`.

Note: `prevClose` falls back to 0 if the endpoint returns null — component already guards `session.open > 0` so same guard applies.
