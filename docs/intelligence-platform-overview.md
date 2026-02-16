# IndicAgent Intelligence Platform — Executive Overview

**Version:** 7.0.0
**Last Updated:** 2026-02-15
**Status:** I1-I6 Operational — 33 Plugins, 178 Tests, Production Ready

## Platform Vision

IndicAgent is an **institutional-grade market intelligence platform** built on microservices architecture with plugin-based intelligence processing — featuring independent, scalable services that communicate via high-performance Redis Streams for real-time trading intelligence.

**Mission**: Extract institutional-quality trading intelligence from real-time market data through hybrid service-plugin processing, preserving 141x performance gains while enabling configurable intelligence expansion for both individual traders and institutional trading systems.

---

## Current Architecture

### Intelligence Status: I1-I6 Complete

**33 registered plugins** across 6 intelligence tiers:

```
FOUNDATION LAYERS (1-7) — OPERATIONAL
├── Data Collection     → IBKR live feeds (ES, NQ, RTY + commodities futures)
├── Event Detection     → Bar completion event triggers
├── Aggregation         → Multi-timeframe bar building (1m→1d)
├── Calculation         → 16 indicator plugins with incremental compute_next()
├── Orchestration       → LangGraph event-driven system coordination
├── Storage             → PostgreSQL/TimescaleDB persistence
└── Distribution        → Redis Streams for external consumption

INTELLIGENCE TIERS — I1-I6 OPERATIONAL
├── I1 Technical Indicators (16 plugins) → RSI, MACD, SMA/EMA, BB, ATR, Stoch, CCI, WilliamsR, MFI, OBV, VWAP, ADX, Keltner, Donchian, ROC/PPO
├── I2 Composite Indicators              → Crossovers, slopes, distances via composites/
├── I3 Market Structure (3 plugins)      → Swing detector (HH/HL/LH/LL), S/R clustering, trend structure
├── I4 Context Classification (3 plugins)→ Volatility regime, trend regime, momentum context
├── I5 Pattern Detection (4 plugins)     → RSI divergence, BB squeeze, volume divergence, confluence
├── I6 Smart Money (6 plugins)           → BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD, HMM regime
├── I6 Cross-Timeframe Confluence (1)    → Trend/structure/regime/pattern alignment across timeframes
├── I7 Trading Outputs                   → NOT YET IMPLEMENTED
└── I8 AI Intelligence                   → NOT YET IMPLEMENTED
```

### Technology Stack

- **Runtime:** Python 3.13, FastAPI 0.129, LangGraph 1.0
- **Data:** DragonflyDB (Redis Streams), TimescaleDB, pandas 3.0
- **Dashboard:** Next.js 15.5 / React 19 / Tailwind v4
- **Monitoring:** Prometheus metrics, circuit breakers, structured logging

---

## What We Have (Production Ready)

### Data Infrastructure
- **Live Data**: IBKR integration with ES/NQ/RTY + commodities futures (24/7 trading)
- **Event-Driven**: Bar completion triggers automatic indicator calculation
- **Multi-Timeframe**: 1m, 5m, 15m, 1h, 4h, 1d analysis across all symbols
- **High Performance**: Redis Streams processing 3,200+ ops/sec, <10ms indicator calculation
- **Time-Series Optimized**: TimescaleDB with hypertable partitioning

### 16 Technical Indicator Plugins (I1)
All with real incremental `compute_next()` — 141x performance boost:
- **Trend**: RSI, MACD, SMA/EMA (multiple periods), ADX/DMI
- **Volatility**: Bollinger Bands, ATR, Keltner Channels, Donchian Channels
- **Momentum**: Stochastic, CCI, Williams %R, ROC/PPO
- **Volume**: MFI, OBV, VWAP

### Market Structure Analysis (I3)
- **Swing Detector**: N=5 neighbor peak/trough detection, HH/HL/LH/LL classification
- **Support/Resistance**: Pivot clustering with strength scoring, nearest S/R levels
- **Trend Structure**: Swing sequence scoring, structural integrity, price position

### Context Classification (I4)
- **Volatility Regime**: ATR percentile ranking, BB width, expansion/contraction detection
- **Trend Regime**: SMA-20/50 alignment + I3 blending → 5-state classification
- **Momentum Context**: Multi-oscillator direction scoring (RSI/MACD/Stoch/CCI bias)

### Pattern Detection (I5)
- **RSI Divergence**: Peak/trough N-neighbor detection, bullish/bearish divergence
- **Bollinger Squeeze**: TTM-style BB-inside-KC with incremental squeeze_count tracking
- **Volume Divergence**: OBV slope vs price slope via linear regression
- **Confluence**: RSI/MACD/Stoch/CCI scoring from -1 to +1

### Smart Money Concepts (I6)
- **BOS/CHoCH**: Break of Structure + Change of Character detection
- **Fair Value Gap**: 3-candle imbalance detection with fill tracking
- **Order Blocks**: Last opposing candle before impulse, strength scoring
- **Liquidity Sweeps**: Wick beyond swing level + close reclaim detection
- **BOCPD Change Point**: Bayesian online change point detection (Adams & MacKay 2007)
- **HMM Regime**: 3-state Hidden Markov Model (ranging/trending-up/trending-down) with multivariate Gaussian emissions and incremental forward algorithm

### Cross-Timeframe Confluence (I6)
- **Alignment Scoring**: Trend, structure, regime, and pattern alignment across 1m/5m/15m/1h
- **Intelligence Cache**: Cross-timeframe state sharing via `intelligence_cache[symbol][timeframe]`

### Terminology: Indicator vs Feature
- **Indicator**: the plugin implementation that computes values (code in `src/intelligence/indicators/`)
- **Feature**: the raw numeric outputs of indicators (I1), published as `features.v1` and optionally persisted to the `features` table (JSONB). Using "features" avoids confusion with composites/patterns and aligns with ML nomenclature.

---

## What We're Building Next

### More Regime & Market Identification (Next Priority)
- GARCH Volatility — conditional volatility forecasting, vol-of-vol regime detection
- Kalman Filter Trend — latent-state trend estimation with adaptive noise filtering
- Chart patterns — double top/bottom, head & shoulders, triangles/wedges

### I7 Trading Outputs
- Setup validation combining I6 confluence with entry/exit criteria
- Signal generation with confidence scoring and risk parameters
- Position sizing recommendations based on volatility regime and HMM state

### I8 AI Intelligence
- OpenRouter LLM integration with cost-controlled processing
- AI-powered pattern interpretation and market narratives
- Market regime detection with confidence scoring

---

## Plugin-Native Intelligence Differentiators

### What Makes Our Architecture Unique

**Plugin-Native Intelligence Engine**: Configuration-driven intelligence pipeline composition
*Differentiator*: Dynamic plugin orchestration vs static service architecture

**Incremental Computation**: All I1 plugins maintain state for O(1) bar updates
*Differentiator*: 141x faster than recalculating from full history each bar

**Probabilistic Regime Detection**: HMM + BOCPD provide complementary regime awareness
*Differentiator*: What regime (HMM) + when it changed (BOCPD) with probabilistic confidence

**Event-Driven Processing**: LangGraph workflows with circuit breakers
*Differentiator*: Real-time stream processing vs batch-based analysis

**Progressive Intelligence**: I1→I6 pipeline refines raw data into structured intelligence
*Differentiator*: Each tier adds context and reduces noise from the tier below

**DAG Execution**: Automatic dependency resolution with parallel execution within stages
*Differentiator*: Plugins declare dependencies; execution order is computed, not hard-coded

---

## Business Value Proposition

### Technical Performance
- **Indicator Calculation**: <10ms per timeframe per symbol (141x via incremental)
- **Stream Throughput**: 3,200+ Redis operations/second
- **Tick Processing**: 500+ ticks/second during RTH
- **End-to-End Latency**: <2 seconds from tick to intelligence distribution
- **Test Coverage**: 178 unit tests passing, 0 lint errors

### Competitive Advantages
- **Individual Traders**: Professional-grade intelligence previously unavailable
- **Institutional Systems**: API-ready intelligence for algorithmic trading integration
- **Scalability**: Plugin-based architecture enables independent scaling of intelligence components
- **Transparency**: Complete intelligence lineage from raw data through pattern detection

---

## Strategic Vision

### Platform Evolution
**Current**: I1-I6 operational with 33 plugins, production-grade infrastructure
**Near-term**: Additional regime models (GARCH, Kalman), chart pattern recognition
**Medium-term**: I7 trading outputs with validated setups and signals
**Long-term**: I8 AI-powered market narratives and institutional-grade insights

### Advanced Capabilities (Future)
- Machine learning plugins with adaptive optimization
- Alternative data integration (sentiment, news, economic indicators)
- Cross-market intelligence through multi-asset analysis
- Portfolio-level intelligence through cross-asset plugin orchestration

---

## References

- **Architecture**: [`docs/architecture/`](architecture/) — Layered architecture, intelligence tiers, plugin registry, stream schemas
- **Current Status**: [`docs/current-status-and-priorities.md`](current-status-and-priorities.md) — Development progress and next priorities
- **Future Indicators**: [`docs/plans/future-indicators-backlog.md`](plans/future-indicators-backlog.md) — Batched indicator backlog
- **Planning**: [`docs/planning/`](planning/) — Historical implementation plans and strategic documents
- **Project Setup**: [`CLAUDE.md`](../CLAUDE.md) — Commands, conventions, and development standards
