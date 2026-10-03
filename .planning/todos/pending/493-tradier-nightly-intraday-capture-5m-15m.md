---
status: pending
priority: P2
filed: 2026-10-03
source: interactive session (owner: near-term nightly backfills come from Tradier)
---

# Nightly Tradier 5m and 15m capture for the recent window

## What

Tradier's intraday history (probed 2026-10-03, sandbox): 1min about 4 weeks, 5min and 15min about 8 weeks,
no 1h. Plan 185-26 moves the nightly 1d leg to Tradier; this todo is the intraday half. A nightly 5m and 15m
fetch for the last few sessions of every name would keep recent bars current without IBKR's pacing, and 15m
and 1h would still derive from 5m in `BarDerivation`. It cannot backfill depth: the HTF lane's 2006 onward
15m and 1h history stays on IBKR.

## Decide first

- Where raw intraday lands (D1 stores 1d only, D-02) and under which source value, after plan 185-25 rebuilds
  `market_data_ohlcv` from real rows.
- The volume seam: Tradier's consolidated volume enters 5m series that IBKR also feeds (a name's daily volume
  already differs by about 20%, todo 492). One source per name per timeframe, or per-bar source flags and a
  rule, before any write.
- Whether a Tradier 5m bar carries the same session edges as the IBKR one (09:30 open, 16:00 close, extended
  hours excluded) so derived 15m and 1h stay session-anchored.

Wait for 185-25 and todo 492 before planning.
