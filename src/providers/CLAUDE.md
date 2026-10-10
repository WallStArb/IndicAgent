# Data Providers — Developer Reference

## Batch history leaves (phase 190)

Vendor batch-history mechanics live in per-vendor leaves satisfying the `HistoryProvider`
protocol (`src/providers/base.py`): `IBKRProvider`, `AlpacaProvider`. Callers dispatch via
`history_leaf(vendor, ...)` (`src/providers/__init__.py`), never a concrete leaf import
outside this ring (CI fence: `tests/unit/test_provider_leaf_boundary.py`). A leaf owns its
vendor's credentials, pagination, native pacing, and symbology; policy never enters a leaf.
Alpaca credentials come from `.env` (`ALPACA_KEY_ID`/`ALPACA_SECRET_KEY`) via Settings;
pacing is APR-backed (`infra.alpaca.rate_limit_max_requests`, migration 469). The nightly
capture runner is `scripts/ops/bars/ops_bar_nightly.py`; the deep-history fetcher is
`scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (provider registry inside).

## IBKR Provider (`ibkr.py`)

All ib_async logic is isolated here. **No ib_async imports anywhere else.**

### Asset Class Rules

| Asset Class | Contract | `whatToShow` | `genericTickList` |
|-------------|----------|--------------|-------------------|
| Futures (`FUT`) | `Future(symbol=...)` | `TRADES` | `"233"` (RTVolume) |
| FX (`CASH`) | `Forex(pair=symbol)` | `MIDPOINT` | `""` |
| Crypto (`CRYPTO`) | `Contract(secType='CRYPTO', symbol=base, currency='USD')` | `AGGTRADES` | `""` |
| Equity/ETF (`STK`) | `Stock(symbol=..., exchange='SMART', currency='USD')` | `TRADES` | `""` |

- VIX futures: `symbol="VXJ6"`, `base="VIX"` (IBKR CFE internal symbol), `provider_meta={"trading_class": "VX"}`. IBKR returns `localSymbol="VXJ6"`. Client IDs: 35+ range.
- Some futures need `tradingClass`: `provider_meta={"trading_class": "XYZ"}`.
- IBKR localSymbol differs for FX/crypto (EUR.USD vs EURUSD) — `_local_to_canonical` dict in `IBKRProvider` handles this; populated in `qualify_instrument`.
- `qualify_instrument` handles `AssetClass.FUTURES` (Future), `.FX` (Forex), `.CRYPTO` (Contract secType='CRYPTO').
- `fetch_historical_bars()` supports `continuous=True` for back-adjusted `ContFuture` data (multi-year backfill).

### Active Contracts
`get_active_contracts(settings, dimension=...)` from `src/config/settings.py` is authoritative; it reads `instruments` (scope columns `compute_eligible`, `compute_eligible_1d`, `live_tradeable`). **Never hardcode counts, they drift fast.**

**The 80-subscription limit is a LIVE-streaming cap, not a backfill cap.** It binds only `reqMktData`/`keepUpToDate` streaming; historical backfill is pacing-limited, not subscription-limited. The streaming provider is dormant (v2.x archive); if it is ever revived, it streams `get_active_contracts(dimension="live")` and refuses to start on an empty or oversized set (phase 174 CR-02). Paper trading unavailable: BZJ6, NGJ6 (NYMEX energy), SR1H6 (SOFR) — Error 200.

### Historical Backfill Chunk Sizes & Rate Limit

`_MAX_CHUNK_DAYS` (per-request duration ceiling per timeframe) and `_IBKR_HIST_RATE_LIMIT` (requests per 10-min sliding window) are APR-governed (`infra.ibkr.chunk_days.*` / `infra.ibkr.rate_limit_max_requests`, `ConfigService`-backed, `config_state` table) — the module-level constants in `ibkr.py` are fallback defaults only, real values load fresh at backfill startup. Current values, all empirically re-verified 2026-08-06 against live IBKR (not inherited assumption — see `production/migrations/302_ibkr_chunk_days_and_rate_limit_recalibration.sql` for full per-key provenance, `production/migrations/303_ibkr_chunk_days_15m_year_rounding_fix.sql` for the 15m correction below, `scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py` to re-test):

| Timeframe | Chunk days | Note |
|-----------|------------|------|
| 1m | 14 | Real IBKR boundary, not inherited guess |
| 5m | 150 | True ceiling is 150-180d (180d confirmed bad) |
| 15m | 730 (2yr) | See migration 303: must be an exact 365 multiple once over 365d |
| 4h | 1095 (3yr) | |
| 1h | 1095 (3yr) | A full-20yr single-shot (7300d) was tested and genuinely FAILED — don't push this one further without new evidence |
| 1d | 7300 (full 20yr, 1 request/symbol) | |

Rate limit: `infra.ibkr.rate_limit_max_requests` = 58 (tested clean to 62, IBKR's own documented hard ceiling is 60 — 58 retains a real margin, not the tested edge).

Per-timeframe limits: `infra.ibkr.rate_limit_max_requests_by_tf` (migration 375, JSON, seeded `{}`) gives a timeframe its own limit and sliding window. IBKR's hard pacing rules bind bars of 30 seconds or less; bars of a minute or more get only a soft slowdown (checked 2026-09-26), so 1d can run above 60 once measured with the probe's `--rate-ceilings`. Head-timestamp lookups stay on the shared limit (as do per-name D1-capture probes during gap-check passes — why a rescan section throttles), and the backfill skips head lookups when every fetched timeframe is a single request (1d). A full-depth 1d window is one request since 2026-09-26 (it was two: an off-by-one date).

`fetch_historical_bars`'s duration-string construction (`"N D"` under 365 days, `"N Y"` over) lives in one shared helper, `_days_to_duration_str()` — both the continuous-contract and regular chunked branches call it. Don't reintroduce a second copy of this logic in either branch; that duplication is exactly how a real bug shipped once (the chunked branch's copy silently didn't exist for years since every prior chunk_days default happened to stay under 365). **Also note:** any `chunk_days.*` value must be an exact multiple of 365 once it crosses the 365-day threshold — otherwise `math.ceil()` rounds the actual IBKR request up past the configured value and the chunking loop's stride desyncs from the real returned window (see 15m above).

### Adding New Contracts
1. Onboard through `onboard_instrument()` via `scripts/infrastructure/universe_expansion_onboard_manifest.py` (manifest CSV; dry run qualifies on IBKR, `--commit` writes). Never INSERT directly: onboarding requires a classification and tags, and insert paths never grant eligibility (migration 352).
2. Backfill: `ohlcv_history_fetcher.py --dimension backfill --timeframes 1d --symbols <list>` (the only IBKR history CLI; it takes FetcherLock, and named symbols are asked even when current).
3. Promote: `universe_expansion_promote_compute_eligible.py --dimension compute_1d --commit` (reads the bar_integrity verdict gate since plan 185-41; see the onboarding SOP).

**Listing-venue moves (todo 433):** SMART history starts at a stock's last primary-venue move. The same conId routed to `NYSE`/`ARCA`/`ISLAND`/`AMEX`/`BATS` serves earlier years with venue-only volume; only the listing venue's closes are official (it carries the most volume). Error 162 "Query failed" is the marker, logged as `ibkr.hist_query_failed`.

### Troubleshooting
- **IB Gateway connection refused**: IB Gateway runs locally via Docker (`ib-gateway` container, `localhost:7497`). If connection fails, check the container is running (`docker ps | grep ib-gateway`) and that the API is enabled inside the gateway UI (VNC on `:5900`).
- **Qualify errors**: Some futures need `tradingClass`: `provider_meta={"trading_class": "XYZ"}` — add it per IBKR's ambiguity message.
