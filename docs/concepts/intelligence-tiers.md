# Intelligence Engine Tiers (I1–I8)

**Current State:** See [STATUS.md](../STATUS.md) for plugin counts and tier status
**Last Updated:** 2026-03-01

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

#### **I2: Composite Events**
**Purpose:** Detect discrete market events from I1 features — runs before I3, results feed I3–I7
**Intelligence Focus:** Crossover events, threshold crosses, band touches, regime signals

- **Input:** I1 raw features
- **Output:** Event flags, bar counts, magnitude readings published into the IntelligenceEvent payload
- **Code Location:** `src/intelligence/composites/`
- **Shared Utilities:** `common.py` — `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`
- **Plugins (5):**
  - `MACDEvents` — MACD line crossovers, histogram sign flips, zero-line crosses
  - `RSIEvents` — overbought/oversold threshold crosses, bars-since tracking
  - `StochasticEvents` — %K/%D crossovers, extreme zone entries/exits
  - `ADXEvents` — ADX strength threshold events, DI+/DI− crossovers
  - `VolumeEvents` — volume spike events, relative-volume threshold crosses

#### **I3: Market Structure Analysis**
**Purpose:** Identify structural patterns, key levels, and price geometry
**Intelligence Focus:** Swing structure, support/resistance, market profile, session levels

- **Input:** OHLCV bars + I1 features
- **Output:** Structure data published into IntelligenceEvent `i3` JSONB field
- **Code Location:** `src/intelligence/structure/`
- **Plugins (7):**
  - `SwingDetector` — HH/HL/LH/LL swing points, trend structure classification
  - `SupportResistance` — pivot-based S/R level clustering with touch counts
  - `TrendStructure` — higher-level trend structure (uptrend / downtrend / ranging)
  - `MarketProfile` — POC, value area high/low, price distribution by volume
  - `SessionLevels` — Asian / London / NY session high, low, midpoint
  - `AnchoredVWAP` — VWAP anchored to swing points or session opens
  - `FibonacciZones` — Fibonacci retracement and extension zones from swing range

#### **I4: Market Context & Regime Detection**
**Purpose:** Classify market environment — volatility state, trend regime, session context
**Intelligence Focus:** Regime labeling, advanced statistical forecasting, multi-timeframe vol

- **Input:** I1/I2/I3 features
- **Output:** Context data published into IntelligenceEvent `i4` JSONB field
- **Code Location:** `src/intelligence/context/`
- **Plugins (7):**
  - `VolatilityRegime` — low / normal / high volatility state from ATR percentile
  - `TrendRegime` — uptrend / downtrend / sideways with ADX-based strength
  - `MomentumContext` — momentum state (accelerating / decelerating / neutral)
  - `GARCHVolatility` — GARCH(1,1) one-step volatility forecast; gates I7 quality checks
  - `KalmanTrend` — 1D Kalman filter, 7 outputs, optional GARCH-adaptive R matrix
  - `SessionContext` — active trading session (Asian / London / NY / overlap)
  - `MTFVolatility` — multi-timeframe volatility spread and compression detection

---

### **Pattern Intelligence (I5-I7)**

#### **I5: Pattern Recognition**
**Purpose:** Detect chart patterns, divergences, squeezes, and confluence conditions
**Intelligence Focus:** Classical chart patterns, momentum divergence, volume analysis, key level reactions

- **Input:** I1–I4 intelligence foundation
- **Output:** Pattern data published into IntelligenceEvent `i5` JSONB field
- **Code Location:** `src/intelligence/patterns/`
- **Plugins (14):**
  - `RSIDivergence` — bullish/bearish RSI divergence vs price
  - `BollingerSqueeze` — low-volatility squeeze detection + breakout direction
  - `VolumeDivergence` — price-volume divergence (rising price / falling volume and inverse)
  - `Confluence` — multi-indicator agreement scorer (RSI + MACD + Stochastic + Volume)
  - `TrendConfluence` — trend-aligned multi-factor confluence scoring
  - `DoubleTopBottom` — double top and double bottom pattern detection
  - `HeadShoulders` — head & shoulders and inverse head & shoulders
  - `TriangleWedge` — ascending / descending / symmetric triangle and wedge patterns
  - `CandlestickPatterns` — engulfing, doji, hammer, shooting star, morning/evening star
  - `FlagPennant` — flag and pennant continuation patterns with pole measurement
  - `CupHandle` — cup and handle accumulation pattern
  - `MeasuredMove` — measured move projection from completed swing segments
  - `VolumeProfile` — volume distribution by price level (POC, VPOC, high-volume nodes)
  - `KeyLevelReaction` — reaction strength at S/R key levels from I3

#### **I6 SMC: Smart Money Concepts**
**Purpose:** Detect institutional order flow signatures — liquidity, structure breaks, order blocks
**Intelligence Focus:** SMC framework: BOS/CHoCH, FVGs, order blocks, liquidity pools, regime detection

- **Input:** I1–I5 intelligence + OHLCV
- **Output:** SMC data published into IntelligenceEvent `smc` JSONB field
- **Code Location:** `src/intelligence/smart_money/`
- **Plugins (13):**
  - `BOS_CHoCH` — break of structure and change of character detection
  - `FairValueGap` — bullish/bearish FVG detection with fill tracking
  - `OrderBlocks` — bullish/bearish order block identification
  - `LiquiditySweeps` — sweep of buyside/sellside liquidity with reclaim confirmation
  - `BOCPDChangepoint` — Bayesian online changepoint detection for regime shifts
  - `HMMRegime` — Hidden Markov Model: ranging(0) / trending(1/2) with probability
  - `LiquidityPools` — equal highs/lows liquidity pool mapping
  - `SupplyDemandZones` — supply and demand zone identification and strength scoring
  - `ICTKillzones` — ICT killzone time windows (London open, NY open, Asian session)
  - `AMDCycle` — Accumulation / Manipulation / Distribution cycle phase detection
  - `BreakerBlocks` — breaker block (failed order block that flips polarity) detection
  - `MitigationBlocks` — mitigation block identification and partial-fill tracking
  - `PremiumDiscount` — premium / discount zone classification relative to range equilibrium

#### **I6 Confluence: Cross-Timeframe Synthesis**
**Purpose:** Aggregate intelligence signals across timeframes into a single confluence score
**Intelligence Focus:** Multi-timeframe trend/structure/regime/pattern/SMC alignment

- **Input:** I1–I6 SMC intelligence across 1m/5m/15m/1h timeframes
- **Output:** Confluence scores published into IntelligenceEvent `i6` JSONB field
- **Code Location:** `src/intelligence/confluence/`
- **Plugins (1):**
  - `CrossTimeframeConfluence` — recency-weighted alignment of trend / structure / regime / pattern / I2 events / SMC BOS sub-score across timeframes; 10 output fields

#### **I7: Trading Setups & Signal Aggregation**
**Purpose:** Fire validated trading setup events; aggregate and score them into a single actionable signal
**Intelligence Focus:** Regime-gated setup detection, 6-bucket scoring, adaptive weight learning

- **Input:** I2–I6 confluence-validated intelligence
- **Output:** Setup events → `signal_ledger` (TimescaleDB); aggregated signal on `signals:SYMBOL:TF:aggregated`
- **Code Location:** `src/intelligence/trading/`
- **Setup Plugins (14):**
  - *Original 9:* `TrendFollowing`, `MeanReversion`, `LiquiditySweepReclaim`, `MTFAlignment`, `SqueezeExpansion`, `VWAPDeviation`, `MomentumBreakout`, `LiquidityHunt`, `SupplyDemandSetup`
  - *CIS contributors (+5):* `CHoCHReversal`, `FVGFill`, `PatternCompletion`, `DivergenceStack`, `RegimeTransition`
  - **Quality gates:** GARCH/Kalman checks on `MeanReversion`, `VWAPDeviation`, `SqueezeExpansion`
- **Signal Aggregation (CISScorer):**
  - Replaces the old winner-pick aggregator
  - 6-bucket weighted scorer: trend / momentum / structure / pattern / institutional / regime
  - **Regime eligibility filter:** trend plugins → trending regime only (HMM 1/2); mean-reversion plugins → ranging regime only (HMM 0); gate bypassed when `hmm_regime_prob < 0.55` or `hmm_regime_duration < 3`
  - **WeightUpdater:** sklearn `LogisticRegression` learns bucket weights from `signal_ledger` outcomes (online adaptive)

---

### **AI Intelligence Synthesis (I8)**

#### **I8: AI Narrative Synthesis**
**Purpose:** Convert I7 signals into human-readable market narratives via 3-tier LLM chain
**Intelligence Focus:** Natural language market analysis, per-signal + asset-group synthesis

- **Input:** High-confidence I7 signals (`confidence > 0.7`) on 5m / 15m / 1h timeframes
- **Output:** Narrative text published to Redis
- **Service:** `services/ai_narrative_service.py` (systemd: `indicagent-ai-narrative`, metrics :9113)
- **Streams:**
  - `narratives:SYMBOL:TF` — per-signal narrative
  - `narratives:group:GROUP_NAME` — 6-asset-group synthesis (equity/energy/metals/rates/fx/crypto)
- **LLM Chain:** ZAI GLM-5 (primary) → OpenRouter (fallback, 100+ models) → Ollama local (offline)
- See [AI Intelligence Architecture](../intelligence/ai-intelligence-architecture.md) for full chain details

---

## **Data Contracts & Stream Architecture**

### **Canonical Stream Keys**
```yaml
indicators:SYMBOL:TF           # I1 output — raw indicator values
intelligence:SYMBOL:TF         # I2–I6 output — typed IntelligenceEvent (tiered JSONB: i1/i3/i4/i5/smc/i6)
signals:SYMBOL:TF:aggregated   # I7 output — CISScorer aggregated signal
narratives:SYMBOL:TF           # I8 output — per-signal AI narrative
narratives:group:GROUP_NAME    # I8 output — asset-group synthesis narrative
```

All keys are env-prefixed (e.g., `development:indicators:ES:1m`) — always build via `src/core/stream_keys.py`.

**Canonical event model:** `IntelligenceEvent` in `src/intelligence/schemas.py` — tiered JSONB (`i1`, `i3`, `i4`, `i5`, `smc`, `i6`), versioned, replaces the old flat string key-value stream messages.

**Reference:** [Stream Schemas](../reference/schemas/stream-schemas.md) — complete field-level specifications

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
- **I2 Composites/Events:** `comp_*` (e.g., `comp_macd_events`, `comp_rsi_events`)
- **I3 Structure:** `struct_*` (e.g., `struct_swings`, `struct_support_resistance`)
- **I4 Context:** `ctx_*` (e.g., `ctx_vol_regime`, `ctx_kalman_trend`)
- **I5 Patterns:** `patt_*` (e.g., `patt_rsi_divergence`, `patt_double_top_bottom`)
- **I6 SMC:** `smc_*` (e.g., `smc_bos_choch`, `smc_fair_value_gap`)
- **I6 Confluence:** `conf_*` (e.g., `conf_cross_timeframe`)
- **I7 Trading:** `setup_*` (e.g., `setup_trend_following`, `setup_mean_reversion`)
- **I8 AI:** `ai_*` (e.g., `ai_narrative`)

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

### **AI Intelligence Framework**
- **I8 Operational:** `ai_narrative_service` running with ZAI GLM-5 (primary), OpenRouter (fallback), Ollama (fallback: qwen3:8b per-signal, group synthesis)
- **LLMChain:** `src/intelligence/llm_providers.py` — ZAIProvider → OpenRouterProvider → OllamaProvider (tries in sequence, exits on first success)

---

## **Intelligence Development Status**

### **Completed Tiers (Production Ready)**

| Tier | Plugins | Notes |
|------|---------|-------|
| I1 Technical Indicators | 23 | RSI, MACD, MA/EMA, Bollinger, ATR, Stochastic, CCI, Williams %R, MFI, OBV, VWAP, Supertrend, PSAR, StochRSI, CMF, Aroon, ChandelierExit, HistoricalVolatility, ROC/PPO, ADX, Keltner, Donchian — all incremental `compute_next()` |
| I2 Composite Events | 5 | MACDEvents, RSIEvents, StochasticEvents, ADXEvents, VolumeEvents |
| I3 Market Structure | 7 | SwingDetector, SupportResistance, TrendStructure, MarketProfile, SessionLevels, AnchoredVWAP, FibonacciZones |
| I4 Context / Regime | 7 | VolatilityRegime, TrendRegime, MomentumContext, GARCHVolatility, KalmanTrend, SessionContext, MTFVolatility |
| I5 Patterns | 14 | RSIDivergence, BollingerSqueeze, VolumeDivergence, Confluence, TrendConfluence, DoubleTopBottom, HeadShoulders, TriangleWedge, CandlestickPatterns, FlagPennant, CupHandle, MeasuredMove, VolumeProfile, KeyLevelReaction |
| I6 SMC | 13 | BOS/CHoCH, FairValueGap, OrderBlocks, LiquiditySweeps, BOCPDChangepoint, HMMRegime, LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount |
| I6 Confluence | 1 | CrossTimeframeConfluence — recency-weighted multi-TF alignment, 10 output fields |
| I7 Trading Setups | 14 + 2 agg | 14 setup plugins (9 original + 5 CIS contributors) + CISScorer aggregator + WeightUpdater |
| I8 AI Narrative | 1 service | `ai_narrative_service` — ZAI GLM-5 → OpenRouter → Ollama (conf>0.7, 5m/15m/1h) + group synthesis |

### **Totals**
- **84 registered plugins + 2 aggregation components:** 23 I1 + 5 I2 + 7 I3 + 7 I4 + 14 I5 + 13 SMC + 1 I6 + 14 I7
- **965 unit tests passing**, 0 ruff errors

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