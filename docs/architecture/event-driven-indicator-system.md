# Plugin-Native Intelligence Processing Architecture

**Version:** 4.0.0
**Last Updated:** 2026-02-14
**Status:** I1-I6 Partial — 31 Plugins Operational, LangGraph Workflows Active

## Executive Summary

IndicAgent's plugin-native intelligence processing system transforms live market data into sophisticated intelligence through event-driven processing with LangGraph workflows. The system implements a complete I1-I8 intelligence framework using plugin-based DAG execution, real-time stream processing, and multi-modal intelligence coordination.

**Core Capability:** Real-time intelligence generation from mathematical features through pattern detection, with 31 registered plugins and 130+ unit tests.

---

## **Plugin-Native Intelligence Architecture**

### **Event-Driven Intelligence Processing**

The plugin-native intelligence processing uses LangGraph workflows with DAG-based plugin execution:

#### **Intelligence Framework**
- `src/intelligence/plugins.py` - Plugin registry with IndicatorPlugin and PatternPlugin protocols
- `src/intelligence/dag.py` - DAG execution engine with dependency resolution
- `src/intelligence/register_plugins.py` - Centralized registration of all 31 plugins
- `src/intelligence/langgraph_event_processor.py` - LangGraph workflow integration with Redis Streams

#### **Stream-Native Processing**
- `src/core/stream_models.py` - Intelligence-aware message processing
- `src/core/unified_market_processor.py` - Primary runtime processor (ingestion → indicators → persistence → publishing)
- `src/core/redis_streams_factory.py` - Factory + async context manager for stream connections
- `src/core/stream_models_core.py` - Core stream dataclasses

#### **Plugin Integration**
- `src/intelligence/indicators/` - 12 indicator plugins with real incremental compute_next()
- `src/intelligence/patterns/` - 4 I5 pattern detection plugins
- `src/intelligence/structure/` - 3 I3 market structure plugins
- `src/intelligence/context/` - 3 I4 context classification plugins
- `services/market_analysis_service.py` - Full I3→I4→I5→SMC→I6 pipeline orchestration (consumes indicators: stream)
- **Performance:** <10ms mathematical processing, 141x speedup via incremental calculations

---

## **Real-Time Intelligence Generation**

```
1. Market Data → IBKR TWS → high_frequency_tws_daemon → market:SYMBOL:TF
                    ↓
2. I1 Indicators → 12 plugins with incremental compute_next() → features:SYMBOL:TF
                    ↓
3. I3 Structure → swing detector, support/resistance, trend structure
                    ↓
4. I4 Context → volatility regime, trend regime, momentum context
                    ↓
5. I5 Patterns → RSI divergence, Bollinger squeeze, volume divergence, confluence
                    ↓
6. Distribution → Redis Streams → Dashboard, External Consumers
```

### **Plugin-Native Processing Benefits**

**Event-Driven Intelligence:**
- LangGraph workflow orchestration with circuit breakers and state management
- DAG-based dependency resolution with parallel execution within stages
- Real-time stream processing via Redis Streams consumer groups

**Real-Time Processing:**
- Sub-10ms mathematical processing with incremental calculations
- Event-driven pattern detection with intelligent state management
- 141x performance boost via state-based incremental compute_next()

**Complete Intelligence Framework:**
- I1-I6 partially operational with 31 registered plugins
- Plugin protocols (IndicatorPlugin, PatternPlugin) enable consistent extension
- Comprehensive test coverage (110 unit tests)

---

## **I1-I8 Intelligence Integration**

### **Intelligence Tier Support**

#### **I1 Raw Features (Operational — 12 plugins)**
**Technical Indicators Calculated:**
- **Trend:** RSI (14), MACD (12/26/9), SMA (20/50/100/200), EMA (8/9/13/21/55)
- **Volatility:** Bollinger Bands (20), ATR (14), Keltner Channels
- **Momentum:** Stochastic (14), CCI (20), Williams %R (14)
- **Volume:** MFI (14), OBV, Volume SMA, VWAP

**Output Streams:** `indicators:SYMBOL:TIMEFRAME`

#### **I2 Composite Indicators (Operational)**
- Moving average crossovers and distances
- Momentum combinations and divergences
- Volatility composite calculations

#### **I3 Market Structure (Operational — 3 plugins)**
- `struct_SwingDetector` — N=5 neighbor peak/trough detection, HH/HL/LH/LL classification
- `struct_SupportResistance` — Pivot clustering with strength scoring, nearest S/R levels
- `struct_TrendStructure` — Swing sequence scoring, structural integrity, price position

#### **I4 Context/Regime (Operational — 3 plugins)**
- `ctx_VolatilityRegime` — ATR percentile ranking, BB width, expansion/contraction detection
- `ctx_TrendRegime` — SMA-20/50 alignment + optional I3 blending, 5-state classification
- `ctx_MomentumContext` — Multi-oscillator direction scoring (RSI/MACD/Stoch/CCI bias)

#### **I5 Pattern Recognition (Operational — 4 plugins)**
- `RSIDivergence` — Peak/trough N-neighbor detection, bullish/bearish divergence
- `BollingerSqueeze` — TTM-style BB-inside-KC, incremental squeeze_count tracking
- `VolumeDivergence` — OBV slope vs price slope via linear regression
- `Confluence` — RSI/MACD/Stoch/CCI scoring from -1 to +1

#### **I6-I8 (Not Yet Implemented)**
- **I6 Confluence & Risk** — Multi-factor scoring combining I3+I4+I5 (next priority)
- **I7 Trading Outputs** — Validated setups and actionable intelligence
- **I8 AI Synthesis** — LLM-powered market narratives and insights

**Reference:** [Intelligence Tiers](intelligence-tiers.md) - Complete I1-I8 specifications

---

## **Event Processing Details**

### **Bar Completion Detection**

**Trigger Events:**
- New 1m bar completion triggers 1m indicator calculations
- 5m boundary (minutes ending 4, 9, 14, 19...) triggers 5m processing
- 15m boundary (minutes ending 14, 29, 44, 59) triggers 15m processing
- Continue for 1h, 4h, 1d timeframe boundaries

### **Multi-Timeframe Coordination**

**Cascading Intelligence Processing:**
1. **1m Bar Complete** → Calculate 1m indicators → I1 Raw Features
2. **5m Boundary** → Aggregate 5m bar → Calculate 5m indicators → I2 Composites
3. **15m Boundary** → Aggregate 15m bar → Multi-timeframe I3 analysis
4. **Higher Timeframes** → Continue pattern for 1h, 4h, 1d intelligence

---

## **Intelligence Distribution**

### **Stream Architecture**

**Foundation Streams (Operational):**
```yaml
market_data: "market:{symbol}:{timeframe}"      # OHLCV bars for all timeframes
indicators: "indicators:{symbol}:{timeframe}"   # I1 Raw Features distribution
```

**Intelligence Streams (I5 Operational, I6+ Future):**
```yaml
patterns: "patterns:{symbol}:{timeframe}"        # I5 pattern intelligence
confluence: "confluence:{symbol}:{timeframe}"    # I6 multi-factor analysis (future)
insights: "insights:{symbol}:{timeframe}"        # I8 AI synthesis (future)
```

---

## **Performance & Reliability**

### **Performance Metrics**
- **Indicator Calculation:** <10ms per timeframe per symbol (141x via incremental)
- **Stream Publishing:** 3,200+ Redis operations/second
- **Data Collection:** 500+ ticks/second processing capability
- **End-to-End Latency:** <2 seconds from tick to intelligence distribution

### **Reliability Features**
- **Circuit Breakers:** Plugin failure handling and recovery via PluginCircuitBreaker
- **LangGraph Workflows:** Event-driven processing with state persistence
- **Service Health Monitoring:** Built-in health checks and Prometheus metrics
- **Consumer Group Reliability:** Redis Streams consumer groups ensure message delivery

---

## **Current Status**

- **31 registered plugins:** 16 indicators + 4 I5 patterns + 3 I3 structure + 3 I4 context + 5 I6 smart money
- **110 unit tests passing**, 0 ruff errors
- **I1-I5 fully operational**, I6-I8 not yet implemented
- **Next priority:** I6 Confluence & Risk — multi-factor scoring combining I3+I4+I5

---

**Related Documentation:**
- [Layered Architecture](layered-architecture.md) - Complete system architecture overview
- [Intelligence Tiers](intelligence-tiers.md) - I1-I8 intelligence processing framework
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Advanced intelligence processing
