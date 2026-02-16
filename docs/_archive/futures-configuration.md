# Futures Configuration - IndicAgent Platform

**Version:** 1.0.0  
**Last Updated:** 2025-08-06  
**Status:** Current Configuration

## TARGET FUTURES CONTRACTS

IndicAgent is configured exclusively for futures trading with **IBKR auto-discovery** of the most active contracts:

### **IBKR-Discovered Active Contracts (August 2025)**

| Symbol | Description | Exchange | Volume | Price | Status |
|--------|-------------|----------|---------|--------|--------|
| **ESU5** | E-mini S&P 500 Sep 2025 | CME | 96,249 | $6,371.25 |  ACTIVE |
| **NQU5** | E-mini Nasdaq Sep 2025 | CME | 56,443 | $23,380.00 |  ACTIVE |
| **ZNU5** | 10-Year Treasury Sep 2025 | CBOT | 242,556 | $112.25 |  ACTIVE |
| **ZBU5** | 30-Year Treasury Sep 2025 | CBOT | 46,291 | $115.69 |  ACTIVE |

### **Additional Futures (Available for Future Integration)**

| Symbol | Description | Exchange | Notes |
|--------|-------------|----------|--------|
| **CL** | Crude Oil WTI | NYMEX | Different naming convention |
| **GC** | Gold | COMEX | Different naming convention |
| **VX** | CBOE VIX Futures | CFE | Different naming convention |
| **NG** | Natural Gas | NYMEX | Different naming convention |

### **Contract Details**

#### **E-mini S&P 500 (ES)**
- **Point Value**: $50 per point
- **Minimum Tick**: 0.25 points ($12.50)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Settlement**: Cash settled

#### **E-mini Nasdaq (NQ)**
- **Point Value**: $20 per point
- **Minimum Tick**: 0.25 points ($5.00)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Settlement**: Cash settled

#### **E-mini Russell 2000 (RTY)**
- **Point Value**: $50 per point
- **Minimum Tick**: 0.10 points ($5.00)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Settlement**: Cash settled

##  **Configuration Files**

### **Data Collection Scripts**

1. **`scripts/production_ibkr_feed.py`**  **NEW: IBKR Auto-Discovery**
   - **Auto-discovers** most active contracts from IBKR
   - Currently finds: ESU5, NQU5, ZNU5, ZBU5
   - Live tick data streaming with volume-based selection
   - Auto-reconnection and error handling
   - Fallback to manual configuration if needed

2. **Database Schema**
   - All tables cleaned of ETF/stock data
   - Optimized for futures symbol naming convention
   - Supports contract rollover

3. **Redis Streams**
   - Stream naming: `market:{SYMBOL}:live` (e.g., `market:ESU5:live`)
   - Timeframe streams: `market:{SYMBOL}:{timeframe}` (e.g., `market:ESU5:1m`)

##  **Data Collection Strategy**

### **Live Data Streams**  **Auto-Discovered**
```
market:ESU5:live    -> Live tick data for ES September 2025 (Vol: 96K)
market:NQU5:live    -> Live tick data for NQ September 2025 (Vol: 56K)
market:ZNU5:live    -> Live tick data for 10Y Treasury Sep 2025 (Vol: 243K)
market:ZBU5:live    -> Live tick data for 30Y Treasury Sep 2025 (Vol: 46K)
```

### **Aggregated Timeframes**
```
market:ESU5:1m      -> 1-minute OHLCV bars
market:ESU5:5m      -> 5-minute OHLCV bars
market:ESU5:15m     -> 15-minute OHLCV bars
market:ESU5:1h      -> 1-hour OHLCV bars
market:ESU5:4h      -> 4-hour OHLCV bars
market:ESU5:1d      -> Daily OHLCV bars
```

##  **Contract Rollover Strategy**

### **September Contracts (U5)**
- **Roll Date**: Typically 8-10 days before expiration (early September 2025)
- **Action**: Switch from ESU5/NQU5/RTYU5 to ESZ5/NQZ5/RTYZ5

### **December Contracts (Z5)**
- **Roll Date**: Typically 8-10 days before expiration (early December 2025)
- **Action**: Switch to March 2026 contracts (H6)

### **Automated Rollover**
- Monitor contract volume and open interest
- Automatically detect front month vs back month
- Update configuration files before expiration

##  **Monitoring & Validation**

### **Data Quality Checks**
1. **Contract Activity**: Ensure active contracts have sufficient volume
2. **Price Continuity**: Monitor for gaps during rollover periods
3. **Tick Frequency**: Validate expected tick rates per contract

### **System Health**
- **Database**: Only futures symbols in market_data_ohlcv table
- **Redis**: Only futures streams active
- **IBKR Connection**: All 6 contracts receiving live data

##  **Important Notes**

1. **No ETFs/Stocks**: Platform exclusively configured for futures
2. **Contract Months**: Focus on front month (U5) and back month (Z5)
3. **Expiration Management**: Monitor rollover dates closely
4. **Symbol Consistency**: Use full contract symbols (ESU5, not ES)

##  **Validation Commands**

```bash
# Check database contents (should only show futures)
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent" python -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/indicagent')
    symbols = await conn.fetch('SELECT DISTINCT symbol FROM market_data_ohlcv ORDER BY symbol')
    print('Futures in database:', [r[0] for r in symbols])
    await conn.close()
asyncio.run(check())
"

# Check Redis streams (should only show futures)
redis-cli --scan --pattern "market:*" | head -10

# Start futures data collection
python scripts/production_ibkr_feed.py
```

---

**Last Updated**: August 5, 2025  
**Status**: Futures-only configuration complete 

## Framework Standard
- Primary orchestration/workflow: LangChain / LangGraph (adopted)
- Actions & tools: LangChain Toolkits (adopted)
- Model routing: LiteLLM + OpenRouter (adopted)