# IndicAgent Hybrid Intelligence Architecture

**Version:** 5.0.0
**Last Updated:** 2026-02-14
**Status:** I1-I5 Production Ready, I3/I4 Context Complete

## Overview

IndicAgent implements a **hybrid intelligence platform** with a clean 4-layer architecture that combines the performance of direct service computation with the flexibility of plugin-based intelligence processing. The platform progresses from raw data collection through sophisticated AI-powered intelligence synthesis using hybrid service-plugin integration.

This document defines the production-ready hybrid architecture that implements the I1-I8 Intelligence Tier framework through strategic integration of plugins INTO existing services rather than replacing them.

## **4-Layer Hybrid Architecture**

### **Layer 1: Data Foundation**
**Purpose:** High-frequency data collection, aggregation, and distribution foundation

**Core Components:**
- `production/daemons/high_frequency_tws_daemon.py` - Live IBKR data collection (100-500+ ticks/sec)
- `services/timeframe_builder_service.py` - Multi-timeframe aggregation (1m→5m→15m→1h→4h→1d)
- `src/core/redis_streams_manager.py` - High-performance stream distribution (3,200+ ops/sec)
- `src/core/database_manager.py` - PostgreSQL/TimescaleDB persistence

**Data Flow:**
```
IBKR TWS → Tick Collection → 1m Bars → Multi-Timeframe Aggregation → Redis Streams
                                    ↓
                           PostgreSQL/TimescaleDB Persistence
```

**Output Streams:** `market:SYMBOL:TIMEFRAME` (all timeframes)
**Intelligence Foundation:** Provides OHLCV data foundation for all I1-I8 intelligence processing
**Status:**  Production Ready - Complete data foundation operational

---

### **Layer 2: Mathematical Intelligence (I1-I4)**
**Purpose:** Hybrid mathematical analysis combining direct performance with plugin flexibility

**Core Components:**
- `services/indicators_processor_service.py` - Hybrid service with direct+plugin processing
- `services/indicators_enhanced_service.py` - 141x performance optimized service
- `src/intelligence/indicators/` - 16 indicator plugins (RSI, MACD, BB, ATR, SMA, EMA, ADX, Keltner, Donchian, ROC/PPO, CCI, Williams%R, Stoch, OBV, VWAP, MFI)
- `src/indicators/incremental_manager.py` - State-based incremental calculations

**Hybrid Processing Strategy:**
```python
class HybridIndicatorProcessor:
    def process_bar(self, bar_data):
        # I1: Direct high-performance calculation (preserve 141x speedup)
        i1_results = self.direct_calculator.calculate_all(bar_data)

        # I2-I4: Plugin-based composite indicators
        i2_4_results = await self.execute_plugins(composite_plugins, bar_data)

        return {**i1_results, **i2_4_results}
```

**Intelligence Processing:**
- **I1 Raw Indicators:** Direct calculation (RSI, MACD, SMA, EMA, ATR, BB) - 141x performance preserved via incremental_manager.py
- **I2 Composite Indicators:** Plugin-based crossovers, slopes, distances, momentum combinations
- **I3 Market Structure:** 3 plugins in `src/intelligence/structure/` — swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure (regime + integrity) -- COMPLETED
- **I4 Context Analysis:** 3 plugins in `src/intelligence/context/` — volatility regime, trend regime, momentum context -- COMPLETED
- **I6 Smart Money:** 6 plugins in `src/intelligence/smart_money/` — BOS/CHOCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime -- PARTIAL

**Output Streams:** `indicators:SYMBOL:TIMEFRAME` (I1 direct), `composite:SYMBOL:TIMEFRAME` (I2-I4 plugins), `patterns:SYMBOL:TIMEFRAME` (I3-I6 plugins)
**Status:** Production Ready - 16 indicator plugins with real incremental compute_next(), I3/I4/I6 partial complete

---

### **Layer 3: Pattern Intelligence (I5-I7)**
**Purpose:** Pure plugin-based pattern recognition and confluence analysis

**Core Components:**
- `src/intelligence/patterns/` - 4 pattern detection plugins (RSI divergence, Bollinger squeeze, volume divergence, confluence)
- `src/intelligence/smart_money/` - 6 smart money plugins (BOS/CHOCH, FVG, order blocks, liquidity sweeps, BOCPD, HMM regime)
- `src/intelligence/confluence/` - Multi-factor confluence analysis (future)
- `src/intelligence/trading/` - Setup validation and signal generation (future)

**Plugin-Native Architecture:**
```python
class PatternDetectionService:
    def __init__(self):
        # Pure plugin execution - no legacy fallback
        self.pattern_plugins = load_pattern_plugins()
        self.confluence_engine = ConfluenceEngine()

    async def process_indicators(self, i1_i4_data):
        # I5-I7: Pure plugin execution
        return await self.execute_pattern_plugins(i1_i4_data)
```

**Intelligence Processing:**
- **I5 Pattern Recognition:** 4 plugins -- RSI divergence (peak/trough N-neighbor), Bollinger squeeze (TTM-style BB-inside-KC), volume divergence (OBV slope vs price slope), multi-indicator confluence scoring -- COMPLETED
- **I6 Confluence Analysis:** Plugin-based multi-timeframe pattern validation, risk-adjusted scoring
- **I7 Trading Signals:** Plugin-based validated setups, actionable intelligence, market opportunities

**Output Streams:** `patterns:SYMBOL:TIMEFRAME` (I5-I7)
**Status:** I5 Complete (4 plugins), I6-I7 not yet implemented

---

### **Layer 4: AI Intelligence (I8)** 
**Purpose:** Future AI service with LLM-powered intelligence synthesis

**Core Components:**
- `services/ai_intelligence_service.py` - Future AI service
- `src/intelligence/ai/` - AI synthesis plugins with OpenRouter integration (future)

**AI Service Architecture:**
```python
class AIIntelligenceService:
    def __init__(self):
        # Future AI service with cost controls
        self.ai_plugins = load_ai_plugins()
        self.cost_manager = CostControlledProcessing()

    async def synthesize_intelligence(self, pattern_data):
        # I8: AI synthesis with cost optimization
        return await self.execute_ai_plugins(pattern_data)
```

**Intelligence Processing:**
- **I8 AI Synthesis:** LLM analysis of I1-I7 intelligence, market narratives
- **Multi-Modal Processing:** Mathematical, pattern, and alternative intelligence coordination
- **Cost Controls:** Intelligent model selection, micro-batching, caching optimization
- **Human-Readable Output:** Natural language insights, intelligence explanations

**Output Streams:** `insights:SYMBOL:TIMEFRAME`, `insights:MARKET`
**Status:**  Framework Ready - Infrastructure implemented, future service planned

---

## **Plugin-Native Intelligence Framework**

### **LangGraph Workflow Engine**
**Purpose:** Event-driven intelligence pipeline orchestration via LangGraph workflows

**Core Components:**
- `src/intelligence/langgraph_event_processor.py` - LangGraph workflow integration with Redis Streams
- `src/intelligence/langgraph_integration.py` - Core LangGraph framework for event-driven intelligence
- `src/intelligence/dag.py` - DAG execution engine with dependency resolution
- `src/config/settings.py` - Centralized application configuration (Settings class)

**Features:**
- **LangGraph Workflows:** Event-driven intelligence processing with state management
- **DAG Execution:** Automatic dependency resolution and execution graphs
- **Circuit Breakers:** Plugin failure handling and recovery
- **Plugin Orchestration:** 33 registered plugins (16 indicators + 17 patterns/structure/context/smart_money) with DAG-aware execution

**Status:** Operational - LangGraph workflows with circuit breakers and monitoring

### **Stream-Native Processing**
**Purpose:** Intelligence-aware stream processing with plugin integration

**Core Components:**
- `src/core/stream_models.py` - Intelligence-aware message processing
- `src/core/unified_market_processor.py` - Primary runtime processor (ingestion -> indicators -> persistence -> publishing)
- `src/core/stream_models_core.py` - Core stream dataclasses
- `src/core/redis_streams_factory.py` - Factory + context manager for stream connections

**Intelligence Streams:**
```python
# Intelligence-aware message processing
class IntelligenceStreamMessage:
    message_type: MessageType  # market_data, indicator, pattern, ai_insight
    intelligence_tier: int     # I1-I8 classification
    processing_context: ProcessingContext
    intelligence_metadata: IntelligenceMetadata
```

**Features:**
- **Intelligence Classification:** Automatic I1-I8 tier detection and routing
- **Message Validation:** Schema validation with intelligent error handling
- **Unified Processing:** Single processor handles ingestion, calculation, persistence, and publishing
- **Performance Monitoring:** Real-time processing metrics and optimization

**Status:** Operational - Unified market processor with stream models

---

## **Plugin-Native Intelligence Flow**

### **4-Layer Intelligence Processing:**
```
Layer 1: Data Foundation
├─ IBKR TWS → High-Frequency Collection → Multi-Timeframe Aggregation
├─ Redis Streams Distribution → market:SYMBOL:TIMEFRAME
└─ PostgreSQL/TimescaleDB Persistence

Layer 2: Mathematical Intelligence (I1-I4)
├─ Plugin Framework → I1 Indicators (RSI, MACD, SMA, etc.)
├─ Composite Processing → I2 Crossovers, I3 Structure, I4 Context
└─ Stream Output → features:SYMBOL:TF, composite:SYMBOL:TF

Layer 3: Pattern Intelligence (I5-I7)
├─ Pattern Detection → I5 Divergences, Breakouts, Smart Money
├─ Confluence Analysis → I6 Multi-Timeframe Validation
├─ Signal Generation → I7 Validated Setups, Intelligence Alerts
└─ Stream Output → patterns:SYMBOL:TIMEFRAME

Layer 4: AI Intelligence (I8)
├─ AI Synthesis → I8 LLM Analysis, Market Narratives
├─ Cost Optimization → Intelligent Model Selection, Caching
├─ Human-Readable Output → Natural Language Insights
└─ Stream Output → insights:SYMBOL:TF, insights:MARKET
```

### **Complete Intelligence Pipeline:**
```
IBKR Data → Layer 1 (Foundation) → market:SYMBOL:TF
                ↓
         Layer 2 (Mathematical) → features:SYMBOL:TF + composite:SYMBOL:TF
                ↓
         Layer 3 (Patterns) → patterns:SYMBOL:TF
                ↓
         Layer 4 (AI) → insights:SYMBOL:TF + insights:MARKET
                ↓
         External Intelligence Consumers
```

### **Configuration-Driven Processing:**
```yaml
# Production intelligence pipeline execution
Pipeline: production_intelligence_pipeline
├─ Stage 1: I1-I4 Mathematical (parallel execution)
├─ Stage 2: I5 Pattern Detection (event-driven)
├─ Stage 3: I6-I7 Confluence + Signals (cross-timeframe)
└─ Stage 4: I8 AI Synthesis (cost-controlled)
```

## **Plugin-Native Dependencies**

### **4-Layer Dependencies:**
- **Layer 1 (Data Foundation)** <- IBKR TWS/Gateway + Settings Configuration
- **Layer 2 (Mathematical Intelligence)** <- Layer 1 + Plugin Framework + LangGraph Workflows
- **Layer 3 (Pattern Intelligence)** <- Layer 2 + DAG Execution + Multi-Timeframe Analysis
- **Layer 4 (AI Intelligence)** <- Layer 3 + OpenRouter Integration (future)

### **Cross-Layer Intelligence Processing:**
- **I1-I4 Mathematical** <- Layer 1 (market data) + Layer 2 (plugin processing)
- **I5-I7 Pattern** <- Layer 2 output + Layer 3 (pattern plugins + confluence analysis)
- **I8 AI Synthesis** <- Layer 3 output + Layer 4 (LLM processing, future)

### **Framework Dependencies:**
- **LangGraph Workflows** <- Plugin Registry + DAG Engine
- **DAG Execution** <- Dependency Resolution + Plugin Registry
- **Stream Processing** <- Unified Market Processor + Intelligence-Aware Streams

## **Plugin-Native Status Summary**

| Layer | Purpose | Status | Core Components | Intelligence Processing |
|-------|---------|--------|-----------------|------------------------|
| **1** | **Data Foundation** | Production Ready | High-frequency collection, aggregation, Redis distribution | Market data foundation for I1-I8 |
| **2** | **Mathematical Intelligence** | Production Ready | 16 indicator plugins with incremental compute_next(), I3 structure (3 plugins), I4 context (3 plugins), I6 smart money (6 plugins) | I1-I4, I6 partial |
| **3** | **Pattern Intelligence** | I5 Complete, I6 Partial | 4 pattern plugins (RSI div, BB squeeze, volume div, confluence) + 6 smart money plugins (BOS/CHOCH, FVG, OB, liq sweeps, BOCPD, HMM) | I5 complete, I6 partial, I7-I8 not implemented |
| **4** | **AI Intelligence** | Architecture Only | AI synthesis planned, OpenRouter integration planned | I8 not implemented |

| Framework Component | Status | Capabilities |
|-------------------|--------|--------------|
| **LangGraph Workflows** | Operational | Event-driven processing, circuit breakers, state management |
| **Stream-Native Processing** | Operational | Unified market processor, intelligence-aware streams |
| **Plugin Integration** | Operational | 53 plugins (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 + 7 I7), DAG execution |
| **Observability** | Operational | Prometheus metrics, OpenTelemetry tracing, structured logging |

## **Development Status & Priorities**

**Production Infrastructure:** Data foundation operational with 16 indicator plugins using real incremental compute_next(), plus 3 I3 structure + 3 I4 context + 4 I5 pattern + 5 I6 smart money plugins
**I3 Market Structure:** COMPLETED -- 3 plugins (swing detector, support/resistance, trend structure)
**I4 Context:** COMPLETED -- 3 plugins (volatility regime, trend regime, momentum context)
**I5 Patterns:** COMPLETED -- 4 plugins (RSI divergence, Bollinger squeeze, volume divergence, confluence)
**22 total plugins** (12 indicators + 10 patterns), **110 unit tests passing**
**Current Priority:** I6 Confluence & Risk -- multi-factor scoring combining I3+I4+I5
**Next Phase:** I7 Trading Outputs, I8 AI intelligence

## **Plugin-Native Intelligence Benefits**

The 4-layer plugin-native architecture with I1-I8 intelligence tiers provides:

### **Technical Excellence:**
- **Clear Intelligence Progression:** Data foundation → Mathematical analysis → Pattern recognition → AI synthesis
- **Plugin-Native Processing:** Configuration-driven intelligence with YAML-based pipeline composition
- **Stream-Native Architecture:** Intelligence-aware message processing with complete lineage tracking
- **Zero-Downtime Updates:** Hot-reloading configuration with resource management and cost controls

### **Intelligence Capabilities:**
- **Progressive Intelligence:** Mathematical foundation → Pattern detection → AI-powered insights
- **Multi-Timeframe Confluence:** Cross-timeframe pattern validation and confidence scoring
- **Event Sourcing:** Complete audit trail with event replay and intelligence lineage tracking
- **Cost-Optimized AI:** Intelligent model selection, micro-batching, and caching optimization

### **Business Intelligence:**
- **Real-Time Processing:** Sub-10ms mathematical processing, event-driven pattern detection
- **Human-Readable Output:** AI-powered market narratives and intelligence explanations
- **External Integration:** Clean APIs for intelligence consumers and external trading systems
- **Multi-Modal Intelligence:** Mathematical, pattern, AI, and alternative intelligence coordination

### **Production Ready:**
- **High-Performance:** 100-500+ ticks/sec collection, 3,200+ ops/sec Redis distribution
- **Service Architecture:** Production-ready systemd services with health monitoring
- **Database Optimization:** PostgreSQL/TimescaleDB with time-series optimization
- **Complete Observability:** Prometheus metrics, OpenTelemetry tracing, structured logging

---

**Related Documentation:**
- [Intelligence Tiers (I1-I8)](intelligence-tiers.md) - Detailed intelligence processing framework
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Plugin-native intelligence framework
- [Comprehensive Intelligence Architecture](comprehensive-intelligence-architecture.md) - Complete system blueprint
- [Stream Schemas](stream-schemas.md) - Redis stream data format specifications