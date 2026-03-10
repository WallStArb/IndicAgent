# Data Providers — Developer Reference

## IBKR Provider (`ibkr.py`)

All ib_insync logic is isolated here. **No ib_insync imports anywhere else.**

### Asset Class Rules

| Asset Class | Contract | `whatToShow` | `genericTickList` |
|-------------|----------|--------------|-------------------|
| Futures (`FUT`) | `Future(symbol=...)` | `TRADES` | `"233"` (RTVolume) |
| FX (`CASH`) | `Forex(pair=symbol)` | `MIDPOINT` | `""` |
| Crypto (`CRYPTO`) | `Contract(secType='CRYPTO', symbol=base, currency='USD')` | `AGGTRADES` | `""` |

- VIX futures: `symbol="VXJ6"`, `base="VIX"` (IBKR CFE internal symbol), `provider_meta={"trading_class": "VX"}`. IBKR returns `localSymbol="VXJ6"`. Client IDs: 35+ range.
- Some futures need `tradingClass`: `provider_meta={"trading_class": "XYZ"}`.
- IBKR localSymbol differs for FX/crypto (EUR.USD vs EURUSD) — `_local_to_canonical` dict in `IBKRProvider` handles this; populated in `qualify_instrument`.
- `qualify_instrument` handles `AssetClass.FUTURES` (Future), `.FX` (Forex), `.CRYPTO` (Contract secType='CRYPTO').
- `fetch_historical_bars()` supports `continuous=True` for back-adjusted `ContFuture` data (multi-year backfill).

### Active Contracts (24)
ES, NQ, RTY, YM (equity index) · CL (energy) · GC, SI, HG, PL (metals) · ZN, ZF, ZB, ZT (rates) · VX (volatility) · ZS, ZC, ZW (agriculture) · EURUSD, GBPUSD, USDJPY, USDCHF (spot FX/IDEALPRO) · BTCUSD, ETHUSD, SOLUSD (spot crypto/PAXOS)

**Always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.**

Paper trading unavailable: BZJ6, NGJ6 (NYMEX energy), SR1H6 (SOFR) — Error 200. NG/BZ valid in live account.
