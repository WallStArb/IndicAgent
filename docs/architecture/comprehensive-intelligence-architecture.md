# IndicAgent Hybrid Intelligence Platform Architecture

**Version:** 7.0.0
**Last Updated:** 2026-02-14
**Status:** I1-I6 Production Ready, I3/I4/I6 Smart Money Partial, 31 Plugins

## Executive Summary

IndicAgent is a **sophisticated market intelligence platform** that transforms raw market data into actionable intelligence through a hybrid service-plugin architecture. The platform combines the performance of direct service computation with the flexibility of plugin-based intelligence processing, enabling both high-performance mathematical processing and configurable intelligence pipeline composition.

**Architecture Philosophy:** Hybrid intelligence extraction combining direct service performance with plugin flexibility, preserving 141x performance gains while enabling configurable intelligence expansion.

---

## Hybrid Intelligence Platform Overview

### Hybrid Service-Plugin Architecture

**Foundation Infrastructure (Layers 1-7):**
High-performance data processing foundation that handles live market data collection, processing, and distribution.

**Hybrid Intelligence Engine:**
Strategic integration of plugins INTO existing services, combining direct high-performance computation with configurable plugin-based processing.

```
FOUNDATION (Operational) → HYBRID ENGINE (Service+Plugin) → INTELLIGENCE (Output)
     ↓                           ↓                               ↓
Data Collection            Hybrid Processing               Multi-Tier Intelligence
Event Processing           Direct: I1 Performance         I1: Direct Calculation
Multi-Timeframe           Plugin: I2-I4 Flexibility      I2-I4: Plugin Processing
Indicator Calculation     Pure Plugin: I5-I7             I5-I7: Plugin Services
Storage & Distribution    Future AI: I8                  I8: AI Services
```

---

## Foundation Infrastructure

### Data Foundation Layer (Layer 1)
**Status:** OPERATIONAL

The foundation provides enterprise-grade market data processing:

- **High-Frequency Data Collection** - IBKR integration with ES/NQ/RTY futures collection (500+ ticks/sec)
- **Multi-Timeframe Aggregation** - Service-based timeframe building: 1m → 5m → 15m → 1h → 4h → 1d
- **Stream Distribution** - Redis Streams publishing with 3,200+ ops/sec throughput
- **Time-Series Storage** - PostgreSQL/TimescaleDB persistence with hypertable optimization
- **Real-Time Processing** - Sub-second data ingestion and distribution pipeline

**Current Implementation Status:**
-  **High-Frequency Collection:** `production/daemons/high_frequency_tws_daemon.py` - Operational
-  **Timeframe Building:** `services/timeframe_builder_service.py` - Operational
-  **Indicator Processing:** `services/indicators_processor_service.py` - Operational with plugin imports
-  **Data Storage:** PostgreSQL/TimescaleDB with hypertables - Operational
-  **Stream Distribution:** Redis Streams with consumer groups - Operational

**Performance Metrics:**
- 500+ ticks/sec data collection
- <10ms indicator calculation latency
- 3,200+ Redis operations/sec throughput
- Multi-timeframe aggregation (1m through 1d)

**Reference:** [Layered Architecture](layered-architecture.md) - Complete infrastructure details

---

## Plugin-Native Intelligence Framework

### Plugin-Native Intelligence Framework
**Status:** Framework Components Implemented, Integration In Progress

#### Current Plugin Infrastructure
- **Plugin Registry:** `src/intelligence/plugins.py` - IndicatorPlugin and PatternPlugin protocols
- **Indicator Plugins:** 12 implemented plugins with real incremental compute_next() (RSI, MACD, SMA/EMA, Bollinger Bands, ATR, Stochastic, CCI, Williams %R, MFI, OBV, VWAP)
- **Pattern Plugins:** 4 I5 pattern plugins in `src/intelligence/patterns/` (RSI divergence, Bollinger squeeze, volume divergence, confluence)
- **Structure Plugins:** 3 I3 structure plugins in `src/intelligence/structure/` (swing detector, support/resistance, trend structure)
- **Context Plugins:** 3 I4 context plugins in `src/intelligence/context/` (volatility regime, trend regime, momentum context)
- **DAG Execution:** `src/intelligence/dag.py` - Dependency resolution and execution graphs
- **Plugin Registration:** `src/intelligence/register_plugins.py` - Centralized plugin registration (33 total: 16 I1 + 3 I3 + 3 I4 + 4 I5 + 6 I6 + 1 CTF)

#### LangGraph Workflow Engine
- **Event Processing:** `src/intelligence/langgraph_event_processor.py` - LangGraph workflow integration with Redis Streams
- **Core Framework:** `src/intelligence/langgraph_integration.py` - Event-driven intelligence orchestration
- **Configuration:** `src/config/settings.py` - Centralized Settings class for all configuration

#### Stream-Native Processing
- **Intelligence Models:** `src/core/stream_models.py` - Intelligence-aware message processing
- **Unified Processor:** `src/core/unified_market_processor.py` - Primary runtime processor (ingestion -> indicators -> persistence -> publishing)
- **Stream Factory:** `src/core/redis_streams_factory.py` - Factory + context manager for stream connections

#### Implementation Status

**Operational Components:**
- **Plugin Framework:** 33 registered plugins (16 indicators + 17 patterns/structure/context/smart_money) with real incremental compute_next()
- **I1 Indicators:** 12 plugins with state-based incremental calculations (141x performance boost)
- **I3 Market Structure:** 3 plugins -- swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure
- **I4 Context:** 3 plugins -- volatility regime, trend regime, momentum context
- **I5 Patterns:** 4 plugins -- RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence
- **LangGraph Workflows:** Event-driven processing with circuit breakers and monitoring
- **Stream Models:** Intelligence-aware message processing via unified_market_processor.py
- **Test Coverage:** 110 unit tests passing, 0 ruff errors

**Not Yet Implemented:**
- I6 Confluence & Risk -- multi-factor scoring combining I3+I4+I5
- I7 Trading Outputs -- setups and signals
- I8 AI Intelligence -- LLM synthesis

**Reference:** [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Complete plugin framework details

---

## AI Intelligence Framework (Layer 4)

### AI Intelligence Architecture
**Status:**  Planned - Framework Ready for Implementation

The AI intelligence layer will provide sophisticated market intelligence synthesis through LLM-powered processing:

#### Planned AI Capabilities
- **Pattern Interpretation** - AI-powered technical pattern analysis and explanation
- **Market Narratives** - Human-readable market intelligence synthesis
- **Sentiment Analysis** - News and market sentiment interpretation
- **Cross-Asset Analysis** - Multi-asset relationship and correlation insights

#### AI Integration Framework (Ready for Implementation)
- **OpenRouter Integration** - Multi-model LLM access with cost optimization (planned)
- **Plugin Architecture** - AI plugins will use same framework as mathematical indicators
- **LangGraph Integration** - Event-driven AI processing via LangGraph workflows

**Current Status:** Infrastructure ready, AI plugins not yet implemented

#### Configuration-Driven AI Processing
- **YAML-Based AI Configuration** - Runtime AI pipeline composition
- **Cost Control Configuration** - Monthly budgets, batch sizes, cooldown periods
- **Trigger-Based Processing** - Event-driven and scheduled AI processing
- **Multi-Model Support** - Plugin-based access to different LLM providers

**Reference:** [Enhanced Intelligence Architecture](enhanced-intelligence-architecture.md) - AI plugin specifications

---

## Plugin-Native Data Flow Architecture

### End-to-End Plugin-Based Intelligence Processing

```
1. Market Data → IBKR TWS → high_frequency_tws_daemon
                    ↓
2. Plugin Integration → indicators_enhanced_service / intelligence_processor_service → Plugin-Based I1-I4 Intelligence
                    ↓
3. Configuration Engine → YAML Pipeline Orchestrator → Dynamic Plugin Composition
                    ↓
4. Stream-Native Processing → Plugin Stream Transformations → I5-I7 Pattern Intelligence
                    ↓
5. AI Plugin Processing → Cost-Controlled AI Plugins → I8 AI Intelligence
                    ↓
6. Event Sourcing → Intelligence Event Store → Complete Audit Trail
                    ↓
7. Distribution → Redis Streams → External Intelligence Consumers
```

### Plugin-Native Stream Architecture
```yaml
# Foundation streams (operational)
market_data: "market:{symbol}:{timeframe}"           # OHLCV data
indicators: "indicators:{symbol}:{timeframe}"        # I1-I4 intelligence

# Plugin-based intelligence streams
features: "features:{symbol}:{timeframe}"            # I1 plugin outputs
composite: "composite:{symbol}:{timeframe}"          # I2-I4 plugin outputs
patterns: "patterns:{symbol}:{timeframe}"            # I5-I7 plugin outputs
insights: "insights:{symbol}:{timeframe}"            # I8 AI plugin outputs

# Configuration and event streams
intelligence_events: "events:intelligence"          # Intelligence event sourcing
plugin_metrics: "metrics:plugins"                   # Plugin performance monitoring
```

**Reference:** [Stream Schemas](stream-schemas.md) - Complete data format specifications

---

## Current Development Status

### Operational Components (Production Ready)
- **Foundation Infrastructure** - Complete data collection + aggregation pipeline
- **Service Architecture** - Production-ready services (indicator processor, timeframe builder, enhanced indicators)
- **Plugin Framework** - 31 registered plugins with IndicatorPlugin and PatternPlugin protocols
- **DAG Execution Engine** - Topological sorting and dependency resolution operational
- **LangGraph Workflows** - Event-driven processing with circuit breakers and state management
- **I1 Indicators** - 12 plugins with real incremental compute_next() (141x performance boost)
- **I3 Market Structure** - 3 plugins: swing detector, support/resistance, trend structure
- **I4 Context** - 3 plugins: volatility regime, trend regime, momentum context
- **I5 Patterns** - 4 plugins: RSI divergence, Bollinger squeeze, volume divergence, confluence

### Next Development Priorities
- **I6 Confluence & Risk** - Multi-factor scoring combining I3+I4+I5 outputs
- **Multi-Timeframe Confluence** - Cross-timeframe validation (1m->5m->15m->1h)

### Ready for Future Implementation
- **I7 Trading Outputs** - Validated setups and actionable intelligence signals
- **I8 AI Intelligence** - OpenRouter LLM framework with cost-controlled processing
- **Advanced Orchestration** - Horizontal scaling for individual plugins with monitoring

---

## Plugin-Native Competitive Advantages

### Technical Excellence
- **Configuration-Driven Intelligence** - Dynamic plugin composition through YAML configuration
- **Stream-Native Processing** - Pure functional stream transformations with real-time processing
- **Plugin-Based Scalability** - Individual intelligence plugins scale independently
- **Intelligence Event Sourcing** - Complete audit trail with lineage tracking and replay capabilities

### Intelligence Sophistication
- **Multi-Modal Intelligence** - Unified framework supporting mathematical, pattern, AI, and alternative intelligence
- **Dynamic Plugin Orchestration** - Runtime intelligence pipeline reconfiguration without system disruption
- **Cost-Controlled AI Processing** - Intelligent batching and resource management for AI plugins
- **Intelligence Transparency** - Complete visibility into intelligence generation process

### Platform Integration
- **Plugin Marketplace Ready** - Framework supports custom intelligence plugin development
- **No-Code Intelligence Pipelines** - YAML-based intelligence composition without programming
- **Horizontal Plugin Scaling** - Independent scaling of intelligence components
- **Real-Time Reconfiguration** - Dynamic intelligence pipeline updates without downtime

---

## Plugin-Native Success Metrics

### Performance Targets
- **Plugin Processing Latency** - <10ms per intelligence calculation
- **Configuration Deployment** - <30 seconds from YAML to production
- **Intelligence Event Sourcing** - <5ms append latency with complete audit trail
- **System Uptime** - >99.9% with plugin-level health monitoring

### Plugin Architecture Quality
- **Dynamic Reconfiguration** - Runtime pipeline updates without service disruption
- **Plugin Composition Flexibility** - Support for custom intelligence workflows through configuration
- **Resource Efficiency** - Intelligent plugin scaling based on demand
- **Cost-Controlled AI Processing** - Intelligent batching maintains <$0.01 per insight

### Development Efficiency
- **Time-to-Market** - New intelligence capabilities deployable through configuration
- **Plugin Development** - Custom intelligence plugins without framework changes
- **Intelligence Transparency** - Complete audit trail enables debugging and optimization
- **Horizontal Scaling** - Individual plugin components scale independently

---

## Related Documentation

### Enhanced Plugin-Native Architecture
- [Enhanced Intelligence Architecture](enhanced-intelligence-architecture.md) - Complete plugin-native specifications
- [Layered Architecture](layered-architecture.md) - Foundation infrastructure details
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Plugin framework implementation
- [Intelligence Tiers](intelligence-tiers.md) - I1-I8 intelligence specifications

### Implementation Guides
- [Development Roadmap](../development-roadmap.md) - Plugin integration phases and timeline
- [Intelligence Platform Overview](../intelligence-platform-overview.md) - Executive overview
- [Stream Schemas](stream-schemas.md) - Data format and event specifications

### Configuration & Setup
- [Market Data Intelligence Configuration](../configuration/market-data-intelligence-configuration.md) - Data sources and processing

---

**Enhanced Architecture Philosophy:** *Leverage existing sophisticated plugin infrastructure with configuration-driven intelligence pipeline composition, enabling rapid deployment of custom intelligence capabilities while maintaining production-grade performance and reliability.*