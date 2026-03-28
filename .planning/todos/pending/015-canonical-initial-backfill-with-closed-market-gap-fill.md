---
created: 2026-03-22T23:24:47.768Z
updated: 2026-03-28T00:00:00.000Z
title: Canonical initial backfill with closed-market gap fill
area: tooling
priority: 15
tier: near-term
files:
  - production/scripts/historical_backfill.py
  - src/providers/ibkr.py
  - src/core/service_utils.py
---

## Problem

After a server restart, `market_data_ohlcv` is empty. The feature pipeline needs
~200 bars per symbol/TF before it can compute indicators (SMA_200, ATR_14, etc.).
Without a seeded history, futures (ES, NQ, etc.) won't produce intelligence events
for hours while bars accumulate live.

The current `historical_backfill.py` has no canonical gap-fill logic at any
timeframe — it stores raw IBKR bars as-is, leaving closed-market gaps in the
series. This causes NaN propagation in rolling window indicators and inconsistent
bar counts across symbols.

The same problem applies to ALL timeframes: 1m, 5m, 15m, 1h, 1d.

## Solution

Rewrite the fetch-and-store stage of `historical_backfill.py` to produce a
**canonical continuous grid** per symbol/TF:

### Fetch depths (native per-TF, not derived)
| TF  | Depth   | IBKR source             |
|-----|---------|-------------------------|
| 1m  | ~30d    | Named contract (IBKR limit) |
| 5m  | 90d     | Named contract          |
| 15m | 180d    | Named contract          |
| 1h  | 365d    | Named contract          |
| 1d  | 2555d   | Named contract (per-contract chain) |

Each TF fetched natively from IBKR — 5m bars are NOT derived from 1m.

### Canonical grid construction
1. Build expected timestamp grid: `[now - depth, now]` at TF interval (e.g. every
   5 min for 5m)
2. Align to exchange sessions using asset class schedule (futures: Sun 6pm ET –
   Fri 5pm ET with 1h break; equities: Mon–Fri 9:30–16:00 ET; FX/crypto: 24h)
3. For each expected slot with no IBKR bar returned:
   - If market is **closed** at that slot → insert synthetic flat bar:
     `O=H=L=C=prev_close, V=0, source='synthetic'`
   - If market is **open** at that slot but IBKR returned nothing → log as a
     true data gap (missing bar, not a closure), flag for gap-fill-service
4. Write canonical series to `market_data_ohlcv` with `source` column to
   distinguish live/fetched/synthetic bars

### Result
- Gapless continuous series for every symbol/TF
- Rolling window indicators (SMA_200, ATR_14, GARCH) initialize correctly
- Feature pipeline produces intelligence immediately after seeding
- `source='synthetic'` flag allows downstream filtering if needed

### Notes
- Distinct from gap-fill-service todo (that handles ongoing gap maintenance;
  this handles cold-start seeding)
- Session schedule logic can be shared when both are implemented
- FX and crypto are 24h — no synthetic bars needed, just any true IBKR gaps
