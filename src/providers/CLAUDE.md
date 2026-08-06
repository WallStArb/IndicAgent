# Data Providers — Developer Reference

> **Status note (2026-07-02): the real-time IBKR provider is not currently running.**
> `indicagent-ibkr-provider` and `provider-merger` are confirmed `inactive (dead)` (v2.x
> real-time pipeline is dormant — see root `CLAUDE.md`). The mechanics below (asset-class
> contract rules, VIX/FX symbol quirks, latency characteristics) remain accurate and directly
> reusable whenever the provider is reactivated or reused in a batch context — only the
> Troubleshooting section's restart instructions assume a currently-running service.

## IBKR Provider (`ibkr.py`)

All ib_async logic is isolated here. **No ib_async imports anywhere else.**

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
`get_active_contracts()` from `src/config/settings.py` is authoritative. As of 2026-08-06: 231 active instruments, all equity asset_class (v3.0 universe expansion, migrations 296/299/301 — up from 111 at the start of that session). **Never hardcode counts, they drift fast.**

**80-subscription limit is a LIVE-streaming cap, not a backfill/registration cap.** IBKR's 80-simultaneous-subscription ceiling applies to `reqMktData`/`reqHistoricalData(keepUpToDate=True)` — i.e. `indicagent-ibkr-provider`'s live path, which is intentionally stopped (see root `CLAUDE.md`'s ingestion-paused note). Historical `reqHistoricalDataAsync` backfill is pacing-limited (`infra.ibkr.rate_limit_max_requests`), not subscription-count-limited — registering and backfilling any number of instruments is fine right now. The gap is real but dormant: 231 active instruments is 151 over the 80-subscription cap, and that must be resolved (retire vs. upgrade the account's subscription tier) **before** `indicagent-ibkr-provider` is ever restarted, not before backfilling.

Paper trading unavailable: BZJ6, NGJ6 (NYMEX energy), SR1H6 (SOFR) — Error 200. NG/BZ valid in live account.

### Historical Backfill Chunk Sizes & Rate Limit

`_MAX_CHUNK_DAYS` (per-request duration ceiling per timeframe) and `_IBKR_HIST_RATE_LIMIT` (requests per 10-min sliding window) are APR-governed (`infra.ibkr.chunk_days.*` / `infra.ibkr.rate_limit_max_requests`, `ConfigService`-backed, `config_state` table) — the module-level constants in `ibkr.py` are fallback defaults only, real values load fresh at backfill startup. Current values, all empirically re-verified 2026-08-06 against live IBKR (not inherited assumption — see `production/migrations/302_ibkr_chunk_days_and_rate_limit_recalibration.sql` for full per-key provenance, `production/migrations/303_ibkr_chunk_days_15m_year_rounding_fix.sql` for the 15m correction below, `scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py` to re-test):

| Timeframe | Chunk days | Note |
|---|---|---|
| 1m | 14 | Real IBKR boundary, not inherited guess |
| 5m | 150 | True ceiling is 150-180d (180d confirmed bad) |
| 15m | 730 (2yr) | 730 = 2×365 exact multiple. Migration 302 originally set this to 400, which crosses the 365d threshold and gets rounded up by `_days_to_duration_str()` to `"2 Y"` (730d) anyway — so 400 and 730 hit the identical IBKR wire request, but the chunking loop's walk-back stride used the literal 400d, causing ~330d of redundant re-fetched overlap per chunk on multi-year backfills. Migration 303 (2026-08-06) fixed this by setting the config value to match what IBKR actually returns. Checked all other chunk_days keys for the same class of bug: 4h/1h (1095d) and 1d (7300d) are exact multiples of 365, no gap; 1m/5m stay under the 365d threshold entirely. 15m was the only affected key. |
| 4h | 1095 (3yr) | |
| 1h | 1095 (3yr) | A full-20yr single-shot (7300d) was tested and genuinely FAILED — don't push this one further without new evidence |
| 1d | 7300 (full 20yr, 1 request/symbol) | |

Rate limit: `infra.ibkr.rate_limit_max_requests` = 58 (tested clean to 62, IBKR's own documented hard ceiling is 60 — 58 retains a real margin, not the tested edge).

`fetch_historical_bars`'s duration-string construction (`"N D"` under 365 days, `"N Y"` over) lives in one shared helper, `_days_to_duration_str()` — both the continuous-contract and regular chunked branches call it. Don't reintroduce a second copy of this logic in either branch; that duplication is exactly how a real bug shipped once (the chunked branch's copy silently didn't exist for years since every prior chunk_days default happened to stay under 365). **Also note:** any `chunk_days.*` value must be an exact multiple of 365 once it crosses the 365-day threshold — otherwise `math.ceil()` rounds the actual IBKR request up past the configured value and the chunking loop's stride desyncs from the real returned window (see 15m above).

### Adding New Contracts
1. Add to `get_active_contracts()` in `src/config/settings.py`
2. INSERT to `instruments` table with `contract_details` JSONB
3. Backfill historical data: see root CLAUDE.md "Historical backfill" command — no service restart needed for this step (live ingestion is paused; `indicagent-ibkr-provider` restart only matters once/if that resumes, and only after the 80-subscription gap above is resolved)

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
