# Intelligence Engine Tiers (I1–I8)

**Current State:** See [STATUS.md](../STATUS.md) for plugin counts and tier status
**Last Updated:** 2026-02-17

## Overview

The Intelligence Engine implements progressive intelligence extraction through eight specialized tiers (I1-I8), each building upon previous tiers to transform raw market data into sophisticated, actionable intelligence. This framework provides the foundation for IndicAgent's market intelligence platform.

**Architecture Philosophy:** Progressive intelligence refinement from mathematical features to AI-powered market insights.

---

## **Intelligence Tier Framework**

### **Mathematical Intelligence Foundation (I1-I4)**

#### **I1: Technical Indicators (Raw Features)**
**Purpose:** Extract mathematical features from raw market data
**Intelligence Focus:** Foundation mathematical analysis of price, volume, momentum, volatility

- **Input:** OHLCV bars
- **Output:** `features.v1` (raw mathematical values: `sma_20`, `ema_21`, `rsi_14`, `atr_14`)
- **Code Location:** `src/intelligence/indicators/`
- **Stream:** `env:features:SYMBOL:TF`
- **Examples:** RSI, MACD, SMA/EMA, Bollinger Bands, ATR, Stochastic, CCI, Williams %R, MFI, OBV

#### **I2: Composite Indicators**
**Purpose:** Create sophisticated indicators from I1 raw features
**Intelligence Focus:** Mathematical relationships and derived intelligence metrics

- **Input:** I1 raw features
- **Output:** `composite.v1` (crossovers, slopes, distances, z-scores, momentum combinations)
- **Code Location:** `src/intelligence/composites/`
- **Stream:** `env:composite:SYMBOL:TF`
- **Examples:** MA crossovers, RSI divergences, momentum confirmations, volatility ratios

#### **I3: Market Structure Analysis**
**Purpose:** Identify structural patterns and key levels in market data
**Intelligence Focus:** Market geometry, support/resistance, swing analysis

- **Input:** OHLCV bars + I1 features
- **Output:** `composite.v1` (swings, pivots, HH/HL/LH/LL patterns, support/resistance touches)
- **Code Location:** `src/intelligence/structure/`
- **Stream:** `env:composite:SYMBOL:TF`
- **Examples:** Swing highs/lows, pivot points, support/resistance levels, trend structure

#### **I4: Market Context & Regime Detection**
**Purpose:** Assess market conditions and regime classification
**Intelligence Focus:** Market environment, volatility states, trend classification

- **Input:** I1/I2/I3 with cross-asset joins
- **Output:** `regime.v1` (trend/volatility regimes), `composite.v1` (technical sentiment)
- **Code Location:** `src/intelligence/context/`
- **Streams:** `env:regime:MARKET|SYMBOL`, `env:composite:SYMBOL:TF`
- **Examples:** Bull/bear/sideways regimes, high/low volatility states, risk-on/off sentiment

---

### **Pattern Intelligence (I5-I7)**

#### **I5: Pattern Recognition (Mathematical & Institutional)**
**Purpose:** Detect sophisticated market patterns and institutional behavior
**Intelligence Focus:** Technical patterns, smart money analysis, institutional flow detection

- **Input:** I1–I4 comprehensive intelligence foundation
- **Output:** `pattern.v1` (divergence, breakout, channel, FVG, liquidity sweep), `composite.v1` (supporting metrics)
- **Code Location:** `src/intelligence/patterns/`
- **Streams:** `env:patterns:SYMBOL:TF`, `env:composite:SYMBOL:TF`
- **Examples:** MACD divergences, fair value gaps, liquidity sweeps, institutional accumulation patterns

#### **I6: Confluence Analysis & Risk Assessment**
**Purpose:** Multi-factor intelligence synthesis and risk evaluation
**Intelligence Focus:** Pattern validation, multi-timeframe confluence, risk-adjusted intelligence

- **Input:** I2–I5 pattern and indicator intelligence
- **Output:** `composite.v1` (confluence scores, risk assessments, confidence metrics)
- **Code Location:** `src/intelligence/confluence/`
- **Stream:** `env:composite:SYMBOL:TF`
- **Examples:** Multi-timeframe pattern agreement, risk-reward ratios, confluence scoring

#### **I7: Intelligence Outputs (Setups & Actionable Intelligence)**
**Purpose:** Generate actionable intelligence and validated setups
**Intelligence Focus:** Market opportunities, setup validation, actionable intelligence insights

- **Input:** I2–I6 confluence-validated intelligence
- **Output:** `pattern.v1` (setup events), `signals` (optional actionable intelligence)
- **Code Location:** `src/intelligence/trading/`
- **Streams:** `env:patterns:SYMBOL:TF`, `env:signals:SYMBOL:TF`
- **Examples:** Validated setups, intelligence alerts, actionable market opportunities

---

### **AI Intelligence Synthesis (I8)**

#### **I8: AI Insights & Synthesis**
**Purpose:** Human-readable intelligence interpretation and market narratives
**Intelligence Focus:** AI-powered market intelligence synthesis, human-readable insights

- **Input:** I2–I7 comprehensive intelligence data
- **Output:** `insight.v1` (market narratives, intelligence summaries, confidence assessments)
- **Code Location:** `src/intelligence/ai/`
- **Streams:** `env:insight:SYMBOL:TF`, `env:insight:MARKET`
- **Examples:** Market narratives, pattern explanations, intelligence summaries, AI-powered market context

---

## **Data Contracts & Stream Architecture**

### **Event Types & Schemas**
```yaml
# Core data contracts
bar.v1:        # OHLCV market data
features.v1:   # I1 raw mathematical features
composite.v1:  # I2-I7 derived intelligence metrics
pattern.v1:    # I5-I7 pattern detection results
regime.v1:     # I4 market regime classification
insight.v1:    # I8 AI intelligence synthesis
```

### **Stream Distribution Patterns**
```yaml
# Foundation data streams
env:features:SYMBOL:TF     # I1 technical indicators
env:composite:SYMBOL:TF    # I2-I7 composite intelligence
env:patterns:SYMBOL:TF     # I5-I7 pattern intelligence
env:regime:MARKET|SYMBOL   # I4 regime detection
env:insight:SYMBOL:TF      # I8 AI synthesis
env:insight:MARKET         # I8 market-wide intelligence
```

**Reference:** [Stream Schemas](stream-schemas.md) - Complete data format specifications

---

## **Processing Architecture**

### **Execution Patterns**

**Fast-Path Processing (I1-I2):**
- **Trigger:** Every completed bar for all timeframes
- **Latency:** <10ms per symbol per timeframe
- **Distribution:** Real-time stream publishing

**Stateful/Event-Driven Processing (I3, I5):**
- **Trigger:** Pattern confirmations and structural changes
- **Processing:** State-based analysis with historical context
- **Distribution:** Event-driven publishing on pattern detection

**Cross-Stream Intelligence (I4, I6-I8):**
- **Processing:** Join nodes with nearest-left matching + tolerance
- **Input:** Multi-timeframe and cross-asset data synthesis
- **Intelligence:** Confluence analysis and comprehensive market intelligence

**AI Intelligence Processing (I8):**
- **Rate Limits:** Cost-controlled LLM usage with micro-batching
- **Optimization:** Caching and intelligent model selection
- **Output:** Human-readable intelligence insights

---

## **Data Persistence & Lineage**

### **Database Schema**
```sql
-- I1 Raw Features
features: {
    timestamp, symbol, timeframe,
    features_data JSONB,  -- Raw mathematical features
    source_stream_ids, plugin_versions
}

-- I2-I8 Intelligence
intelligence: {
    timestamp, symbol, timeframe, intelligence_tier,
    intelligence_data JSONB,  -- Processed intelligence
    source_stream_ids, compute_plan_id, plugin_versions,
    confidence_score, lineage_metadata
}
```

### **Intelligence Lineage**
- **Source Tracking:** `source_stream_ids` for complete intelligence provenance
- **Compute Plans:** `compute_plan_id` for processing workflow tracking
- **Version Management:** `plugin_versions` for intelligence reproducibility
- **Quality Metrics:** Confidence scoring and validation tracking

---

## **Development Conventions**

### **Code Organization**
```
src/intelligence/
├── indicators/     # I1 technical indicator plugins
├── composites/     # I2 composite indicator calculations
├── structure/      # I3 market structure analysis
├── context/        # I4 regime and sentiment detection
├── patterns/       # I5 pattern recognition engines
├── confluence/     # I6 multi-factor analysis
├── trading/        # I7 actionable intelligence outputs
└── ai/            # I8 AI synthesis and insights
```

### **Plugin Naming Conventions**
- **I1 Indicators:** `indi_*` (e.g., `indi_rsi`, `indi_macd`)
- **I2 Composites:** `comp_*` (e.g., `comp_ma_crossover`, `comp_momentum_combo`)
- **I3 Structure:** `struct_*` (e.g., `struct_swings`, `struct_support_resistance`)
- **I4 Context:** `ctx_*` (e.g., `ctx_regime`, `ctx_volatility_state`)
- **I5 Patterns:** `patt_*` (e.g., `patt_macd_divergence`, `patt_smart_money`)
- **I6 Confluence:** `conf_*` (e.g., `conf_multi_timeframe`, `conf_risk_assessment`)
- **I7 Trading:** `trad_*` (e.g., `trad_setup_validator`, `trad_intelligence_alerts`)
- **I8 AI:** `ai_*` (e.g., `ai_pattern_interpreter`, `ai_market_narrative`)

### **Capability Tags**
```python
# Plugin capability classification
capability_tags = {
    "trend", "momentum", "volatility", "volume",        # Mathematical
    "structure", "institutional", "context",            # Market analysis
    "synthesis", "intelligence", "ai_powered"           # Advanced intelligence
}
```

---

## **Intelligence Platform Integration**

### **Service Architecture Integration**
The I1-I8 framework integrates seamlessly with IndicAgent's service-based architecture:

- **Data Foundation:** `indicators_processor_service` (and `indicators_enhanced_service`) provide I1 raw features
- **Intelligence Processing:** Plugin framework handles I2-I8 advanced intelligence
- **Distribution:** Redis Streams distribute intelligence across all tiers
- **Consumption:** External intelligence consumers access processed intelligence

### **AI Intelligence Framework (Planned)**
- **Multi-Agent System:** I8 tier will implement AI agent coordination
- **OpenRouter Integration:** Cost-optimized LLM access for intelligence synthesis (planned)
- **Human-Readable Output:** AI-powered market narratives and intelligence explanations (planned)

---

## **Intelligence Development Status**

### **Completed Tiers (Production Ready)**
- **I1 Technical Indicators:** 12 plugins with real incremental compute_next() -- RSI, MACD, SMA/EMA, Bollinger, ATR, Stochastic, CCI, Williams %R, MFI, OBV, VWAP (141x performance boost)
- **I2 Composite Indicators:** Crossovers, slopes, distances via `src/intelligence/composites/`
- **I3 Market Structure:** 3 plugins in `src/intelligence/structure/` -- swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure (regime + integrity)
- **I4 Context/Regime:** 3 plugins in `src/intelligence/context/` -- volatility regime (ATR percentile, BB width), trend regime (SMA alignment + I3 blending), momentum context (multi-oscillator scoring)
- **I5 Pattern Recognition:** 4 plugins in `src/intelligence/patterns/` -- RSI divergence (peak/trough N-neighbor), Bollinger squeeze (TTM-style), volume divergence (OBV vs price), multi-indicator confluence

- **SMC Smart Money:** 6 plugins in `src/intelligence/smart_money/` -- BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime
- **I6 Cross-Timeframe Confluence:** 1 plugin in `src/intelligence/confluence/` -- trend/structure/regime/pattern alignment scoring across 1m/5m/15m/1h

### **Not Yet Implemented**
- **I7 Intelligence Outputs:** Validated setups and actionable intelligence signals
- **I8 AI Synthesis:** OpenRouter LLM integration for market narratives and insights

### **Totals**
- **32 registered plugins:** 16 indicators + 4 I5 patterns + 3 I3 structure + 3 I4 context + 5 SMC smart money + 1 I6 confluence
- **172 unit tests passing**, 0 ruff errors

---

## **Intelligence Framework Benefits**

### **Progressive Intelligence**
- **Clear Progression:** Mathematical foundation → Pattern recognition → AI synthesis
- **Modular Design:** Each tier can be developed and enhanced independently
- **Quality Assurance:** Built-in confidence scoring and validation at each tier

### **Technical Excellence**
- **Real-Time Processing:** Sub-second intelligence generation across all tiers
- **Scalable Architecture:** Plugin-based system supports unlimited intelligence capabilities
- **Data Lineage:** Complete intelligence provenance and reproducibility

### **Business Intelligence**
- **Actionable Insights:** From raw math to human-readable intelligence insights
- **Multi-Timeframe Intelligence:** Comprehensive analysis across all trading timeframes
- **External Integration:** Clean APIs for intelligence consumers and external systems

---

**Related Documentation:**
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Intelligence processing framework
- [Stream Schemas](stream-schemas.md) - Complete data format specifications
- [AI Intelligence Architecture](../intelligence/ai-intelligence-architecture.md) - AI synthesis implementation