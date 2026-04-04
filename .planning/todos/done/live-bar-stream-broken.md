---
title: Fix live bar stream — RTBs never work, switch to official bars as primary
priority: critical
created: 2026-04-04
---

## Problem

The live bar stream has been **broken since Phase 54 (March 28)** when `IBKRAdapter` was introduced.

- `reqRealTimeBars` callbacks from IBKR/TWS never fire → `stream_bars()` blocks forever on `bar_queue.get()`
- `provider_bars_produced_total = 0` (confirmed via Prometheus on restart)
- All 1.9M messages in `market.bars.raw.ibkr` are `source=ibkr_named` (gap fills only)
- Pipeline has been running entirely on historical backfill data, zero live bars

The asyncio queue bridge mechanism itself is correct (tested). IBKR/TWS simply doesn't deliver 5s RTB callbacks in the current setup.

## Also fixed in this session (already committed)

- `stream_official_bars`: changed crypto from `TRADES` → `AGGTRADES` (was error 10299)
- `stream_official_bars`: skip crypto entirely (`AGGTRADES + keepUpToDate=True` = error 321)
- DB: rolled SIH6→SIK6, HGH6→HGK6 as front months (61/61 qualify now)

## Required fix

**In `src/providers/ibkr_adapter.py` — make `stream_official_bars` the primary bar source:**

### Non-crypto symbols
`stream_official_bars(keepUpToDate=True, whatToShow=TRADES)` WORKS. Change `_official_bars_background()` inside `stream_bars()` to emit bars directly to `bar_queue` instead of only populating `_official_bars_cache`.

### Crypto (BTCUSD, ETHUSD)
`keepUpToDate=True + AGGTRADES` = error 321. Two options:
1. **Polling fallback**: add `_crypto_poll_loop()` that calls `fetch_historical_bars(symbol, "1m", now-3min, now)` every 65s for crypto symbols; deduplicate via existing `_seen_ts` guard
2. Accept no live crypto bars (only gap-fill coverage)

### RTB path
Can be removed or kept as dead code — it never worked and is not worth debugging unless specifically needed.

## Key files
- `src/providers/ibkr_adapter.py` — `stream_bars()` method (~lines 93-344)
- `src/providers/ibkr.py` — `stream_official_bars()` (~lines 641-720), `stream_real_time_bars()` (~lines 590-639)

## Verification
After fix, watch for `source=ibkr_generic` bars in `market.bars.raw.ibkr`:
```
docker exec redpanda rpk topic consume market.bars.raw.ibkr --offset end --num 5 --format "%v\n" \
  | python3 -c "import sys,json; [print(json.loads(l).get('source'), json.loads(l).get('symbol'), json.loads(l).get('ts')) for l in sys.stdin if l.strip()]"
```
And check `provider_bars_produced_total` metric at http://localhost:9129/metrics.
