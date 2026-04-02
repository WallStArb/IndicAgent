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

### Active Contracts (60)
**Futures (16):** ES, NQ, RTY, YM (equity index) · CL (energy) · GC, SI, HG (metals) · ZN, ZF, ZB, ZT (rates) · VX (volatility) · ZS, ZC, ZW (agriculture)
**FX (4):** EURUSD, GBPUSD, USDJPY, USDCHF (spot/IDEALPRO, session_id=fx_24_5)
**Crypto (2):** BTCUSD, ETHUSD (spot/PAXOS, session_id=crypto_24_7)
**ETFs (38, SMART, session_id=nyse):** SPY, QQQ, IWM, DIA · XLF, XLK, XLE, XLC, XLY, XLV, XLI, XLU, XLRE, XLP, XLB · TLT, IEF, SHY, HYG, LQD, EMB · GLD, SLV, USO · SMH, IBB, GDX, GDXJ, XOP, ITB · MTUM, QUAL, VLUE, USMV · EFA, EEM, EWZ, FXI
*(IBKR default subscription limit is 80 — 20 slots headroom at 60 instruments)*

**Always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.**

Paper trading unavailable: BZJ6, NGJ6 (NYMEX energy), SR1H6 (SOFR) — Error 200. NG/BZ valid in live account.

### Adding New Contracts
1. Add contract to `get_active_contracts()` in `src/config/settings.py`
2. INSERT to `instruments` table with `contract_details` JSONB:
   ```sql
   INSERT INTO instruments (symbol, contract_details) 
   VALUES ('ESM6', '{"exchange":"CME","currency":"USD",...}'::jsonb);
   ```
3. Restart `indicagent-ibkr-provider`
4. Verify qualification: `journalctl -u indicagent-ibkr-provider | grep "Qualified"`
5. Backfill historical data: see root CLAUDE.md "New contracts" command

### Testing Provider Changes
```bash
# Test provider connection
.venv/bin/python -m src.providers.ibkr --test-connection

# Verify bars are flowing
journalctl -u indicagent-ibkr-provider --since "1 minute ago" | grep "1m bar emitted"

# Check Kafka output
docker exec redpanda rpk topic consume market.bars.raw.ibkr --from-end
```

### Troubleshooting
- **TWS connection refused**: IBKR TWS at `192.168.1.157` — check trusted IPs in TWS API settings if connection fails.
- **Contract rollover**: When futures expire (H6→M6/J6), restart `indicagent-ibkr-provider` to load new contracts:
  ```bash
  sudo systemctl restart indicagent-ibkr-provider
  # Verify: journalctl -u indicagent-ibkr-provider | grep "KafkaProducerClient started"
  ```
- **`bars_processed` freeze**: TWS daemon gets stuck — IBKR paper account returns stale RTH bars regardless of `endDateTime` format. `seen_bar_timestamps` dedup caches all timestamps from initial poll; counter sticks at N×61 forever. **Restart does NOT fix it.** Root fix: build 1m OHLCV bars from live tick stream (`development.market.ticks`) instead of polling historical API.
- **Qualify errors**: Some futures need `tradingClass` in `provider_meta` — add if IBKR returns ambiguous contract details.
- **LocalSymbol mismatches**: FX/crypto use dots (EUR.USD) vs codebase (EURUSD) — `_local_to_canonical` dict handles this automatically.
