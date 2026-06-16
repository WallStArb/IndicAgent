# Data Providers — Developer Reference

## IBKR Provider (`ibkr.py`)

All ib_insync logic is isolated here. **No ib_insync imports anywhere else.**

### Asset Class Rules

| Asset Class | Contract | `whatToShow` | `genericTickList` |
|-------------|----------|--------------|-------------------|
| Futures (`FUT`) | `Future(symbol=...)` | `TRADES` | `"233"` (RTVolume) |
| FX (`CASH`) | `Forex(pair=symbol)` | `MIDPOINT` | `""` |
| Crypto (`CRYPTO`) | `Contract(secType='CRYPTO', symbol=base, currency='USD')` | `AGGTRADES` | `""` |
| Equity/ETF (`STK`) | `Stock(symbol=..., exchange='SMART', currency='USD')` | `TRADES` | `"233"` (RTVolume) |

- VIX futures: `symbol="VXJ6"`, `base="VIX"` (IBKR CFE internal symbol), `provider_meta={"trading_class": "VX"}`. IBKR returns `localSymbol="VXJ6"`. Client IDs: 35+ range.
- Some futures need `tradingClass`: `provider_meta={"trading_class": "XYZ"}`.
- IBKR localSymbol differs for FX/crypto (EUR.USD vs EURUSD) — `_local_to_canonical` dict in `IBKRProvider` handles this; populated in `qualify_instrument`.
- `qualify_instrument` handles `AssetClass.FUTURES` (Future), `.FX` (Forex), `.CRYPTO` (Contract secType='CRYPTO').
- `fetch_historical_bars()` supports `continuous=True` for back-adjusted `ContFuture` data (multi-year backfill).

### Active Contracts
Count drifts with futures rolls — `get_active_contracts()` from `src/config/settings.py` is authoritative. As of last update: ~63 instruments (~21 futures, 4 FX, 38 ETFs). IBKR subscription limit 80. **Never hardcode counts.**

Paper trading unavailable: BZJ6, NGJ6 (NYMEX energy), SR1H6 (SOFR) — Error 200. NG/BZ valid in live account.

### Adding New Contracts
1. Add to `get_active_contracts()` in `src/config/settings.py`
2. INSERT to `instruments` table with `contract_details` JSONB; restart `indicagent-ibkr-provider`
3. Backfill historical data: see root CLAUDE.md "New contracts" command

### Bar Delivery Latency

Live bars come from `reqHistoricalDataAsync(keepUpToDate=True)` via `stream_official_bars()`. This is a reconciliation API, not a low-latency feed. Observed delivery: **~5-6s from bar open** (`bar.ts`) to `market.bars` Kafka topic, all bars under 10s (measured via `merger_bar_latency_seconds`).

**What this means:** IBKR fires `updateEvent(has_new_bar=True)` when a new bar period starts (at `:00`), delivering the newly-opened bar's initial snapshot ~5-6s later. This is IBKR server-side latency — nothing in our stack adds to it. The `merger_bar_latency_seconds` metric measures provider delivery lag (bar.ts → merger receipt), not merger processing time (which is sub-millisecond pass-through).

**Trade-off accepted:** `keepUpToDate=True` gives clean, audited 1m bars suitable for signal computation. `reqRealTimeBars` (5s RTBs) would give sub-second delivery but requires bar accumulation and adds pipeline complexity. For 1m signal logic this latency is acceptable; for sub-second price display it is not.

### Troubleshooting
- **IB Gateway connection refused**: IB Gateway runs locally via Docker (`ib-gateway` container, `localhost:7497`). If connection fails, check the container is running (`docker ps | grep ib-gateway`) and that the API is enabled inside the gateway UI (VNC on `:5900`).
- **Contract rollover**: When futures expire (H6→M6/J6), restart `indicagent-ibkr-provider` to load new contracts:
  ```bash
  sudo systemctl restart indicagent-ibkr-provider
  # Verify: grep "KafkaProducerClient started" logs/ibkr_provider_agent.log | tail -3
  ```
- **`bars_processed` freeze**: TWS daemon gets stuck — IBKR paper account returns stale RTH bars regardless of `endDateTime` format. `seen_bar_timestamps` dedup caches all timestamps from initial poll; counter sticks at N×61 forever. **Restart does NOT fix it.** Root fix: build 1m OHLCV bars from live tick stream (`development.market.ticks`) instead of polling historical API.
- **Qualify errors**: Some futures need `tradingClass` in `provider_meta` — add if IBKR returns ambiguous contract details.
- **LocalSymbol mismatches**: FX/crypto use dots (EUR.USD) vs codebase (EURUSD) — `_local_to_canonical` dict handles this automatically.
