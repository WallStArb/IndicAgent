# Intelligence Platform Dashboard

**Version:** 2.0.0  
**Last Updated:** 2026-02-12  
**Status:** Current - I5 patterns, structure, and context panels operational

Real-time futures trading dashboard with live pattern detection, market structure, context classification, and technical analysis.

## Features

**Futures-Focused Intelligence:**
- **ES, NQ, RTY Futures**: Primary instruments with 24/7 institutional flow data
- **Multi-timeframe Analysis**: 1m precision to 15m signals to 1h context (1m, 5m, 15m, 1h, 4h, 1d)
- **Technical Indicators**: 12 indicator plugins with automatic calculation engine (I1)
- **Pattern Detection (I5)**: RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence
- **Market Structure (I3)**: Swing detector, support/resistance, trend structure
- **Context Classification (I4)**: Volatility regime, trend regime, momentum context
- **Real-time Updates**: SSE or Socket.IO (env-configurable via `NEXT_PUBLIC_USE_SSE`) from IndicAgent API

**Intelligence Platform Integration:**
- **Foundation Layer**: Live technical indicators with incremental calculation (141x performance)
- **Pattern Layer**: I5 mathematical pattern detection (divergence, squeeze, confluence)
- **Structure & Context**: I3 structure and I4 context panels
- **Future AI Layer**: Pattern interpretation and market context (I8 planned)
- **External API Ready**: Built for trading system integration

## Layout

The dashboard is built from:

- **Price hero** – Current price, change, trend
- **Indicator grid** – RSI, MACD, SMA/EMA, BB, ATR, Stoch, Williams %R, VWAP, MFI, CCI, etc.
- **Pattern panel** – I5 pattern detection status and signals
- **Structure panel** – I3 swing/structure and S/R context
- **Context panel** – I4 regime and momentum context

Data is driven by the IndicAgent backend (SSE or Socket.IO). Timeframe selector updates indicators and panels for the selected timeframe.

## Usage

### Development Mode

```bash
# From dashboard directory
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Ensure the IndicAgent backend and (optionally) Socket.IO server are running for live data.

### Production Build

```bash
npm run build
npm start
```

### Real-time Connection

The dashboard uses either:

- **SSE** – When `NEXT_PUBLIC_USE_SSE=true`, connects to the backend `/api/sse` endpoint
- **Socket.IO** – Otherwise connects to `http://localhost:8001` (indicagent-websocket service)

Subscribed streams (backend consumes and forwards):

- `ticks:SYMBOL:live` – Real-time price updates
- `market:SYMBOL:TIMEFRAME` – OHLCV bar data
- `indicators:SYMBOL:TIMEFRAME` – Technical indicator values

## Timeframe Switching

Use the timeframe selector to switch between 1m, 5m, 15m, 1h, 4h, 1d. Indicator and panel data update for the selected timeframe.

## Monitored Instruments

**Primary Futures (24/7 Trading):**
- **ES**: S&P 500 E-mini Futures
- **NQ**: Nasdaq 100 E-mini Futures
- **RTY**: Russell 2000 E-mini Futures

**Focus**: Futures provide continuous institutional flow data for pattern detection, structure, and context analysis.

## Dependencies

- Next.js 15.4+
- React 19.1+
- Socket.IO Client (optional; SSE alternative)
- Tailwind CSS v4
- Lucide React Icons
- shadcn/ui

## Intelligence Platform Integration

**Current Integration (Production Ready):**
- **Live Data Pipeline**: IBKR futures to Redis Streams to technical indicators and intelligence services
- **Automatic Calculation**: 12 indicator plugins in real-time (incremental, 141x faster)
- **I3/I4/I5**: Structure, context, and pattern plugins via intelligence processor service
- **Real-time Bridge**: SSE or Socket.IO with sub-second latency

**Planned (I6–I8):**
- **I6 Confluence & Risk**: Multi-factor scoring and risk assessment
- **I7 Trading Outputs**: Setups and signals
- **I8 AI Intelligence**: LLM synthesis and interpretation

**Technical Architecture:**
- Next.js 15.4 with React 19 for real-time rendering
- SSE primary; Socket.IO client as fallback (env-driven)
- TypeScript with futures and indicator data models
- Tailwind v4 and shadcn for responsive, trading-oriented UI
