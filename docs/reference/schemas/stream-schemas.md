# Intelligence Stream Schemas & Data Contracts

**Version:** 2.1.0
**Last Updated:** 2026-02-12
**Status:** Schema Specifications — bar.v1 and features.v1 operational, remaining schemas defined for future tiers

## Executive Summary

This document defines the complete data contracts for IndicAgent's intelligence processing streams. Each schema supports specific intelligence tiers (I1-I8) and enables sophisticated market intelligence processing through standardized, versioned data structures.

**Core Purpose:** Standardized data contracts that enable seamless intelligence processing from raw market data to AI-powered insights. I1-I5 schemas are in production use; I6-I8 are defined for future tiers.

**Runtime stream names (code):** The app builds stream names in `src/core/stream_keys.py`. Current patterns use an optional env prefix plus: `ticks:SYMBOL:live`, `market:SYMBOL:TIMEFRAME`, `indicators:SYMBOL:TIMEFRAME`, `intelligence:SYMBOL:TIMEFRAME`. So Redis keys are `market/` (OHLCV bars), `indicators/` (I1 output), `intelligence/` (I3/I4/I5 output), and `ticks/` (live ticks). The names in the "Data Flow Architecture" section below (bar, features, composite, etc.) are schema/contract names; implementation uses the stream_keys patterns.

---

## **Schema Architecture Principles**

### **Design Standards**
- **Versioned Schemas:** All schemas include explicit versioning for backward compatibility
- **Intelligence Tier Mapping:** Each schema aligns with specific I1-I8 intelligence processing tiers
- **Stream Optimization:** Compact msgpack encoding for high-performance Redis Streams distribution
- **Database Integration:** JSONB storage format for flexible PostgreSQL/TimescaleDB persistence
- **Field Conventions:** snake_case keys, UTC timestamps, numeric precision standards

### **Data Flow Architecture**
```yaml
# Stream naming pattern: env_prefix:data_type:symbol:timeframe
prod:bar:ES:1m           # Foundation market data
prod:features:ES:1m      # I1 Raw Features
prod:composite:ES:5m     # I2-I7 Composite Intelligence
prod:patterns:ES:15m     # I5-I7 Pattern Intelligence
prod:regime:MARKET       # I4 Market Context
prod:insight:ES:1h       # I8 AI Intelligence
```

---

## **Foundation Data Schemas**

### **`bar.v1` - Market Data (OHLCV)**
**Intelligence Tier:** Foundation (Feeds I1-I8)
**Schema Version:** `bar/1.0`
**Stream Pattern:** `env:bar:SYMBOL:TIMEFRAME`

```python
{
    "type": "bar.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol (e.g., "ES", "NQ", "RTY")
    "timeframe": str,                 # Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
    "timestamp": str,                 # UTC ISO-8601 timestamp
    "open": float,                    # Opening price
    "high": float,                    # Highest price
    "low": float,                     # Lowest price
    "close": float,                   # Closing price
    "volume": int,                    # Trading volume
    "source": str,                    # Data source (e.g., "ibkr", "polygon")
    "data_quality_score": float       # Quality assessment (0.0-1.0)
}
```

**Example:**
```json
{
    "type": "bar.v1",
    "schema_version": "1.0.0",
    "symbol": "ES",
    "timeframe": "5m",
    "timestamp": "2025-08-10T14:30:00Z",
    "open": 4521.25,
    "high": 4523.75,
    "low": 4520.50,
    "close": 4522.00,
    "volume": 15420,
    "source": "ibkr_live",
    "data_quality_score": 0.98
}
```

---

## **Intelligence Processing Schemas**

### **`features.v1` - I1 Raw Features (Mathematical Indicators)**
**Intelligence Tier:** I1 Raw Features
**Schema Version:** `features/1.0`
**Stream Pattern:** `env:features:SYMBOL:TIMEFRAME`

```python
{
    "type": "features.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol
    "timeframe": str,                 # Analysis timeframe
    "timestamp": str,                 # UTC timestamp of bar
    "features": {                     # Flat map of mathematical features
        "sma_20": float,             # Simple Moving Average (20)
        "ema_21": float,             # Exponential Moving Average (21)
        "rsi_14": float,             # Relative Strength Index (14)
        "macd": float,               # MACD Line
        "macd_signal": float,        # MACD Signal Line
        "macd_histogram": float,     # MACD Histogram
        "bb_upper": float,           # Bollinger Band Upper
        "bb_middle": float,          # Bollinger Band Middle (SMA 20)
        "bb_lower": float,           # Bollinger Band Lower
        "atr_14": float,             # Average True Range (14)
        "stoch_k": float,            # Stochastic %K
        "stoch_d": float,            # Stochastic %D
        "volume_sma_20": float,      # Volume Simple Moving Average (20)
        # Additional features as needed...
    },
    "source": str,                   # Processing source/plugin
    "compute_plan_id": str,          # DAG execution identifier
    "plugin_versions": dict,         # Plugin version tracking
    "processing_latency_ms": float   # Processing performance metric
}
```

**Example:**
```json
{
    "type": "features.v1",
    "schema_version": "1.0.0",
    "symbol": "ES",
    "timeframe": "5m",
    "timestamp": "2025-08-10T14:30:00Z",
    "features": {
        "sma_20": 4518.75,
        "ema_21": 4519.85,
        "rsi_14": 67.3,
        "macd": 2.15,
        "macd_signal": 1.85,
        "macd_histogram": 0.30,
        "bb_upper": 4525.40,
        "bb_middle": 4518.75,
        "bb_lower": 4512.10,
        "atr_14": 3.85,
        "volume_sma_20": 12450.0
    },
    "source": "indicator_processor_v2.1.0",
    "compute_plan_id": "dag_exec_12345",
    "plugin_versions": {"rsi": "1.0.0", "macd": "1.1.0"},
    "processing_latency_ms": 8.5
}
```

### **`composite.v1` - I2-I7 Composite Intelligence**
**Intelligence Tier:** I2 Composite Indicators through I7 Setup Intelligence
**Schema Version:** `composite/1.0`
**Stream Pattern:** `env:composite:SYMBOL:TIMEFRAME`

```python
{
    "type": "composite.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol
    "timeframe": str,                 # Analysis timeframe
    "timestamp": str,                 # UTC timestamp
    "intelligence_tier": str,         # I2, I3, I4, I5, I6, or I7
    "composite_type": str,            # Type of composite intelligence
    "values": dict,                   # Composite calculations
    "confidence": float,              # Intelligence confidence (0.0-1.0)
    "source_features": list,          # Source I1 features used
    "rationale": str,                 # Human-readable explanation
    "attributes": dict,               # Additional intelligence metadata
    "source": str,                    # Plugin/processor identifier
    "compute_plan_id": str           # DAG execution tracking
}
```

**I2 Composite Example (MA Crossover):**
```json
{
    "type": "composite.v1",
    "schema_version": "1.0.0",
    "symbol": "ES",
    "timeframe": "15m",
    "timestamp": "2025-08-10T14:30:00Z",
    "intelligence_tier": "I2",
    "composite_type": "ma_crossover_bullish",
    "values": {
        "fast_ma": 4519.85,
        "slow_ma": 4515.20,
        "crossover_strength": 0.73,
        "distance_points": 4.65,
        "duration_bars": 3
    },
    "confidence": 0.82,
    "source_features": ["ema_21", "sma_50"],
    "rationale": "EMA21 crossed above SMA50 with strong momentum",
    "attributes": {
        "crossover_angle": 15.6,
        "volume_confirmation": true
    },
    "source": "composite_ma_crossover_v1.0.0",
    "compute_plan_id": "dag_exec_12346"
}
```

---

## **Advanced Intelligence Schemas**

### **`pattern.v1` - I5-I7 Pattern Intelligence**
**Intelligence Tier:** I5 Pattern Recognition, I6 Confluence, I7 Setup Validation
**Schema Version:** `pattern/1.0`
**Stream Pattern:** `env:patterns:SYMBOL:TIMEFRAME`

```python
{
    "type": "pattern.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol
    "timeframe": str,                 # Analysis timeframe
    "timestamp": str,                 # Pattern detection timestamp
    "intelligence_tier": str,         # I5, I6, or I7
    "pattern_type": str,              # Pattern classification
    "confidence": float,              # Pattern confidence (0.0-1.0)
    "rationale": str,                 # Pattern explanation
    "attributes": dict,               # Pattern-specific attributes
    "confluence_factors": list,       # Supporting confluence elements
    "risk_reward_ratio": float,       # Risk/reward assessment
    "invalidation_level": float,      # Pattern invalidation price
    "target_levels": list,            # Price targets
    "source": str,                    # Detection plugin
    "validation_status": str          # Pattern validation state
}
```

**I5 Pattern Example (MACD Divergence):**
```json
{
    "type": "pattern.v1",
    "schema_version": "1.0.0",
    "symbol": "ES",
    "timeframe": "1h",
    "timestamp": "2025-08-10T14:00:00Z",
    "intelligence_tier": "I5",
    "pattern_type": "macd_bullish_divergence",
    "confidence": 0.87,
    "rationale": "Price making lower lows while MACD making higher lows over 4-bar sequence",
    "attributes": {
        "divergence_strength": 0.76,
        "lookback_bars": 15,
        "price_swing_low_1": 4505.25,
        "price_swing_low_2": 4503.75,
        "macd_swing_low_1": -1.85,
        "macd_swing_low_2": -1.22,
        "confirmation_bar": true
    },
    "confluence_factors": ["rsi_oversold", "support_level_touch"],
    "risk_reward_ratio": 2.4,
    "invalidation_level": 4501.00,
    "target_levels": [4515.00, 4525.00, 4535.00],
    "source": "pattern_macd_divergence_v2.1.0",
    "validation_status": "confirmed"
}
```

### **`regime.v1` - I4 Market Context Intelligence**
**Intelligence Tier:** I4 Context & Regime Detection
**Schema Version:** `regime/1.0`
**Stream Pattern:** `env:regime:SCOPE` (MARKET or SYMBOL:TIMEFRAME)

```python
{
    "type": "regime.v1",
    "schema_version": "1.0.0",
    "scope": str,                     # "MARKET" or "ES:15m"
    "timestamp": str,                 # Assessment timestamp
    "intelligence_tier": "I4",
    "trend_regime": str,              # "bullish", "bearish", "sideways"
    "volatility_regime": str,         # "low", "normal", "high", "extreme"
    "market_structure": str,          # "trending", "ranging", "breakout"
    "confidence": float,              # Regime confidence (0.0-1.0)
    "regime_strength": float,         # Strength of current regime (0.0-1.0)
    "expected_duration": str,         # Expected regime duration
    "rationale": str,                 # Regime assessment explanation
    "supporting_indicators": list,    # Indicators supporting assessment
    "regime_change_probability": float, # Probability of regime change
    "source": str                     # Regime detection plugin
}
```

**Example:**
```json
{
    "type": "regime.v1",
    "schema_version": "1.0.0",
    "scope": "ES:15m",
    "timestamp": "2025-08-10T14:30:00Z",
    "intelligence_tier": "I4",
    "trend_regime": "bullish",
    "volatility_regime": "normal",
    "market_structure": "trending",
    "confidence": 0.79,
    "regime_strength": 0.82,
    "expected_duration": "2-4 hours",
    "rationale": "Strong uptrend with consistent higher highs and higher lows, normal volatility expansion",
    "supporting_indicators": ["ema_slope_positive", "atr_normalized", "volume_above_average"],
    "regime_change_probability": 0.15,
    "source": "regime_detector_v1.2.0"
}
```

### **`insight.v1` - I8 AI Intelligence Synthesis**
**Intelligence Tier:** I8 AI Insights & Human-Readable Intelligence
**Schema Version:** `insight/1.0`
**Stream Pattern:** `env:insight:SYMBOL:TIMEFRAME` or `env:insight:MARKET`

```python
{
    "type": "insight.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol or "MARKET"
    "timeframe": str,                 # Analysis timeframe or "MULTI"
    "timestamp": str,                 # Insight generation timestamp
    "intelligence_tier": "I8",
    "insight_type": str,              # Type of AI insight
    "summary": str,                   # Human-readable insight summary
    "narrative": str,                 # Detailed market narrative
    "key_factors": list,              # Primary intelligence factors
    "confidence": float,              # AI confidence in insight
    "evidence_sources": list,         # Source intelligence tiers/patterns
    "market_context": dict,           # Current market environment
    "actionable_intelligence": dict,  # Specific actionable insights
    "risk_assessment": dict,          # Risk evaluation
    "model_metadata": {               # AI processing metadata
        "model_id": str,
        "cost_usd": float,
        "latency_ms": int,
        "evidence_hash": str,
        "token_usage": dict
    },
    "source": str                     # AI intelligence agent
}
```

**Example:**
```json
{
    "type": "insight.v1",
    "schema_version": "1.0.0",
    "symbol": "ES",
    "timeframe": "1h",
    "timestamp": "2025-08-10T14:30:00Z",
    "intelligence_tier": "I8",
    "insight_type": "pattern_confluence_analysis",
    "summary": "Strong bullish confluence detected with MACD divergence, regime support, and institutional accumulation patterns",
    "narrative": "ES is exhibiting a compelling bullish setup with multiple confirming factors. The MACD bullish divergence identified at the 1-hour level shows strong momentum confirmation, while the current bullish regime provides structural support. Volume profile analysis indicates institutional accumulation near key support levels.",
    "key_factors": [
        "MACD bullish divergence (confidence: 0.87)",
        "Bullish trend regime (confidence: 0.79)",
        "Institutional accumulation pattern",
        "Volume confirmation above average"
    ],
    "confidence": 0.84,
    "evidence_sources": ["I5_macd_divergence", "I4_regime_bullish", "I6_confluence_analysis"],
    "market_context": {
        "overall_sentiment": "risk_on",
        "volatility_environment": "normal",
        "institutional_flow": "accumulation"
    },
    "actionable_intelligence": {
        "primary_scenario": "Continuation of bullish momentum with targets at 4515, 4525",
        "risk_management": "Invalidation below 4501 support level",
        "confluence_score": 0.82,
        "expected_duration": "4-8 hours"
    },
    "risk_assessment": {
        "risk_reward_ratio": 2.4,
        "probability_success": 0.76,
        "max_adverse_excursion": 8.5
    },
    "model_metadata": {
        "model_id": "gpt-4-0613",
        "cost_usd": 0.0087,
        "latency_ms": 1240,
        "evidence_hash": "sha256:abc123def456",
        "token_usage": {"input": 1850, "output": 420}
    },
    "source": "ai_confluence_agent_v1.0.0"
}
```

---

## **Schema Validation & Standards**

### **Validation Rules**
```python
# Common validation patterns
SYMBOL_PATTERN = r"^[A-Z]{2,6}$"                    # 2-6 uppercase letters
TIMEFRAME_PATTERN = r"^(1m|5m|15m|30m|1h|4h|1d)$"   # Supported timeframes
TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"  # UTC ISO-8601

# Numeric validation ranges
CONFIDENCE_RANGE = (0.0, 1.0)                      # Confidence scores
RSI_RANGE = (0.0, 100.0)                          # RSI values
PRICE_PRECISION = 2                                # Price decimal places
VOLUME_TYPE = int                                  # Volume as integer
```

### **Error Handling**
- **Schema Validation:** All events validated against schema before processing
- **Data Quality Scoring:** Automated quality assessment for all market data
- **Graceful Degradation:** Invalid events logged but don't halt processing
- **Version Compatibility:** Backward compatibility maintained across schema versions

---

## **Implementation Status**

### **Current Status**
- **`bar.v1`** - Operational in production with IBKR live data
- **`features.v1`** - Operational with 12 indicator plugins (legacy format)
- **`composite.v1`** - Schema defined, not yet implemented
- **`regime.v1`** - Schema defined, not yet implemented

### **Schema Gaps**
- **`pattern.v1`** - Schema defined, pattern detection engines not yet implemented
- **Advanced composite.v1** - I5-I7 intelligence schemas defined, engines not yet implemented
- **Cross-timeframe patterns** - Multi-timeframe schemas defined, processing not yet implemented

### **Architecture Complete**
- **`insight.v1`** - AI intelligence schema defined, OpenRouter integration not yet implemented
- **Database integration** - Enhanced storage schemas defined, not yet deployed to production
- **Stream distribution** - Redis Streams operational, intelligence-aware streams not yet integrated

---

## **Related Documentation**

- [Intelligence Tiers (I1-I8)](intelligence-tiers.md) - Intelligence processing framework
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Processing architecture
- [Intelligence Processing Architecture](event-driven-indicator-system.md) - Service integration
- [Layered Architecture](layered-architecture.md) - Complete system overview

---

**Schema Philosophy:** *Standardized, versioned data contracts enable seamless intelligence processing from raw market data through sophisticated AI-powered insights, supporting unlimited intelligence capabilities through consistent, extensible schemas.*


