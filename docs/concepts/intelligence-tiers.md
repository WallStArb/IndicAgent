# Intelligence Engine Tiers (I1–I8)

**Current State:** See [STATUS.md](../STATUS.md) for plugin counts and tier status
**Last Updated:** 2026-04-22

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
- **Stream:** `{env}:indicators:SYMBOL:TF`
- **Examples:** RSI, MACD, SMA/EMA, Bollinger Bands, ATR, Stochastic, CCI, Williams %R, MFI, OBV

#### **I2: Composite Events**
**Purpose:** Detect discrete market events from I1 features — runs before I3, results feed I3–I7
**Intelligence Focus:** Crossover events, threshold crosses, band touches, regime signals

- **Input:** I1 raw features
- **Output:** Event flags, bar counts, magnitude readings published into the IntelligenceEvent payload
- **Code Location:** `src/intelligence/composites/`
- **Shared Utilities:** `common.py` — `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`
- **Plugins (10):**
  - `RSIEvents` — overbought/oversold threshold crosses, bars-since tracking
  - `StochasticEvents` — %K/%D crossovers, extreme zone entries/exits
  - `ADXEvents` — ADX strength threshold events, DI+/DI− crossovers
  - `VolumeEvents` — volume spike events, relative-volume threshold crosses
  - `MomentumAccel` — acceleration/deceleration state from momentum composite; produces `rsi_curvature` + `macd_hist_slope` for AccelerationRegime
  - `DonchianPos` — price position relative to Donchian channel bounds
  - `OBVMomentum` — OBV trend direction and momentum score
  - `DerivOscillator (AO)` — Awesome Oscillator: fast vs slow momentum
  - `ExhaustionScore` — multi-indicator exhaustion scoring (overbought/oversold composite)
  - `AccelerationRegime` — sign-vote momentum acceleration regime: building / peak / trough / waning / neutral; outputs `accel_regime`, `accel_score`, `accel_agreement`

#### **I3: Market Structure Analysis**
**Purpose:** Identify structural patterns, key levels, and price geometry
**Intelligence Focus:** Swing structure, support/resistance, market profile, session levels

- **Input:** OHLCV bars + I1 features
- **Output:** Structure data published into IntelligenceEvent `i3` JSONB field
- **Code Location:** `src/intelligence/structure/`
- **Plugins (8):**
  - `MACDEvents` — MACD line crossovers, histogram sign flips, zero-line crosses (placed here because MACD requires I1 + structural context)
  - `SwingDetector` — HH/HL/LH/LL swing points, trend structure classification
  - `SupportResistance` — pivot-based S/R level clustering with touch counts
  - `TrendStructure` — higher-level trend structure (uptrend / downtrend / ranging)
  - `MarketProfile` — POC, value area high/low, price distribution by volume
  - `SessionLevels` — Asian / London / NY session high, low, midpoint
  - `FibonacciZones` — Fibonacci retracement and extension zones from swing range
  - `SwingMomentum` — momentum at swing highs/lows, provides divergence context for I5 patterns

#### **I4: Market Context & Regime Detection**
**Purpose:** Classify market environment — volatility state, trend regime, session context
**Intelligence Focus:** Regime labeling, advanced statistical forecasting, multi-timeframe vol, cross-asset context

- **Input:** I1/I2/I3 features
- **Output:** Context data published into IntelligenceEvent `i4` JSONB field
- **Code Location:** `src/intelligence/context/`
- **Plugins (12):**
  - `VolatilityRegime` — low / normal / high volatility state from ATR percentile
  - `TrendRegime` — uptrend / downtrend / sideways with ADX-based strength
  - `MomentumContext` — momentum state (accelerating / decelerating / neutral)
  - `GARCHVolatility` — GARCH(1,1) one-step volatility forecast; gates I7 quality checks; runs in Wave A so `garch_sigma` is available to `KalmanTrend`
  - `HurstExponent` — R/S analysis over 64-bar window; H>0.65 = trending, H<0.35 = mean-reverting; hard gate for I7 setup eligibility
  - `ShannonEntropy` — return distribution entropy; high entropy = noise/random, low entropy = structured regime; universal signal confidence gate
  - `KalmanTrend` — 1D Kalman filter, 7 outputs, GARCH-adaptive R matrix (Wave B — depends on `garch_sigma`)
  - `SessionContext` — active trading session (Asian / London / NY / overlap)
  - `AnchoredVWAP` — VWAP anchored to swing points or session opens (`ctx_AnchoredVWAP`)
  - `VolumeProfile` — session and rolling volume distribution: POC, VAH, VAL, high/low-volume nodes (`ctx_VolumeProfile`)
  - `VIXRegime` — VIX-based macro volatility regime classification; cross-asset fear gauge
  - `CrossAssetContext` — cross-asset correlation and divergence signals (equities, bonds, commodities)

---

### **Pattern Intelligence (I5-I7)**

#### **I5: Pattern Recognition**
**Purpose:** Detect chart patterns, divergences, squeezes, and confluence conditions
**Intelligence Focus:** Classical chart patterns, momentum divergence, volume analysis, key level reactions

- **Input:** I1–I4 intelligence foundation
- **Output:** Pattern data published into IntelligenceEvent `i5` JSONB field
- **Code Location:** `src/intelligence/patterns/`
- **Plugins (16):**
  - `MTFVolatility` — multi-timeframe volatility spread and compression detection
  - `RSIDivergence` — bullish/bearish RSI divergence vs price
  - `BollingerSqueeze` — low-volatility squeeze detection + breakout direction
  - `VolumeDivergence` — price-volume divergence (rising price / falling volume and inverse)
  - `MACDDivergence` — bullish/bearish MACD histogram divergence vs price
  - `CMFDivergence` — Chaikin Money Flow divergence vs price
  - `Confluence` — multi-indicator agreement scorer (RSI + MACD + Stochastic + Volume)
  - `TrendConfluence` — trend-aligned multi-factor confluence scoring
  - `DoubleTopBottom` — double top and double bottom pattern detection
  - `HeadShoulders` — head & shoulders and inverse head & shoulders
  - `TriangleWedge` — ascending / descending / symmetric triangle and wedge patterns
  - `CandlestickPatterns` — engulfing, doji, hammer, shooting star, morning/evening star
  - `FlagPennant` — flag and pennant continuation patterns with pole measurement
  - `CupHandle` — cup and handle accumulation pattern
  - `MeasuredMove` — measured move projection from completed swing segments
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
- **Output:** Setup events → `intelligence.i7.signals` (Kafka) → `signal_ledger` (TimescaleDB via `SignalWriterAgent`)
- **Code Location:** `src/intelligence/trading/`
- **Setup Plugins (36):**
  - *Core 9:* `TrendFollowing`, `MeanReversion`, `LiquiditySweepReclaim`, `MTFAlignment`, `SqueezeExpansion`, `VWAPDeviation`, `MomentumBreakout`, `LiquidityHunt`, `SupplyDemandSetup`
  - *CIS contributors (+5):* `CHoCHReversal`, `FVGFill`, `PatternCompletion`, `DivergenceStack`, `RegimeTransition`
  - *Session/structure (+3):* `GapAnalysis`, `CandlestickPatternSetup`, `SessionExtremes`
  - *Breakout/continuation (+5):* `FailedBreakout`, `ORB15`, `ORB30`, `PrevDayLevelTest`, `SecondLegContinuation`
  - *Volume profile (+5):* `VCP`, `AnchoredVWAPReversion`, `VWAPReclaim`, `POCRejection`, `HVNRejection`, `LVNBreakout` (6)
  - *Microstructure (+7):* `OFIContinuation`, `OFIDivergence`, `OFISpike`, `CVDDivergence`, `CVDSpike`, `DeltaExhaustion`, `DualDivergence`
  - *Cross-asset (+1):* `CrossAssetDivergence`
  - **Quality gates:** GARCH/Kalman checks on `MeanReversion`, `VWAPDeviation`, `SqueezeExpansion`
  - **`regime_type` required** on all I7 plugins: `"trend"` | `"mean_reversion"` | `"any"` — used by the regime gate
- **Signal Aggregation (CISScorer):**
  - Replaces the old winner-pick aggregator
  - 6-bucket weighted scorer: trend / momentum / structure / pattern / institutional / regime
  - **Regime eligibility filter:** trend plugins → trending regime only (HMM 1/2); mean-reversion plugins → ranging regime only (HMM 0); gate bypassed when `hmm_regime_prob < REGIME_PROB_MIN` (settings-configurable, default 0.30) or `hmm_regime_duration < REGIME_DUR_MIN` (default 1 bar)
  - **Setup performance multiplier:** Sharpe-ranked weights loaded from `signal_metrics` table at startup and every hour; governs which setup plugin wins when multiple eligible signals fire (see [CIS Scoring](cis-scoring.md))

---

### **AI Intelligence Synthesis (I8)**

#### **I8: AI Narrative Synthesis**
**Purpose:** Convert I7 signals into human-readable market narratives via 3-tier LLM chain
**Intelligence Focus:** Natural language market analysis, per-signal + asset-group synthesis

- **Input:** High-confidence I7 signals from `intelligence.journal` topic
- **Output:** Narrative text published to `narratives` Kafka topic (keyed `SYMBOL:TF`)
- **Service:** `services/ai_narrative_agent.py` (systemd: `indicagent-ai-narrative`)
- **Topics:**
  - `narratives` (keyed `SYMBOL:TF`) — per-signal narrative
  - `narratives.group` — 6-asset-group synthesis (equity/energy/metals/rates/fx/crypto)
- **LLM Chain:** OpenRouter (primary, free models) → Ollama gemma4:e4b (offline fallback)
- **Audit:** Every LLM call published to `llm.calls` → `indicagent-llm-writer` persists to `llm_calls` hypertable

---

## **Data Contracts & Stream Architecture**

### **Canonical Stream Keys**
```yaml
intelligence            # I1–I7 output — typed IntelligenceEvent (tiered JSONB: i1/i3/i4/i5/smc/i6), keyed SYMBOL:TF
intelligence.i7.signals # I7 output — all ranked signals per bar (pre-ledger write), keyed SYMBOL:TF
intelligence.journal    # I7 high-confidence signals routed to AI narrative (I8 input)
intelligence.lifecycle  # LifecycleTransition events from SignalTrackerComputeAgent
intelligence.signal_metrics  # Signal performance stats from SignalMetricsComputeAgent
narratives              # I8 output — per-signal AI narrative, keyed SYMBOL:TF
narratives.group        # I8 output — asset-group synthesis narrative
llm.calls               # Every LLM call audit record
llm.outcomes            # Signal exit events for back-filling LLM call outcomes
```

All topics are env-prefixed with a dot separator (e.g., `development.intelligence`) — always build via `src/core/stream_keys.py`.

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

## **Code Organization**

```
src/intelligence/
├── indicators/     # I1 technical indicator plugins
├── composites/     # I2 composite event plugins
├── structure/      # I3 market structure plugins
├── context/        # I4 regime and context plugins
├── patterns/       # I5 pattern recognition plugins
├── smart_money/    # I6 SMC plugins
├── confluence/     # I6 cross-timeframe confluence plugin
└── trading/        # I7 setup plugins, CISScorer, aggregator, shared utilities
```

Plugin names use short descriptive `PascalCase` matching the class name (e.g., `RSI`, `KalmanTrend`, `BOS_CHoCH`). I4 context plugins are prefixed `ctx_` in the registry (e.g., `ctx_AnchoredVWAP`), I7 setup plugins use `trad_` (e.g., `trad_TrendFollowing`). See `src/intelligence/register_plugins.py` for canonical names.

---

## **Intelligence Platform Integration**

### **Service Architecture Integration**
The I1-I8 framework integrates seamlessly with IndicAgent's service-based architecture:

- **Unified Intelligence Pipeline:** `indicagent-intelligence-pipeline` (`intelligence_pipeline_agent.py`) runs I1–I7 fully in-process per bar; outputs `intelligence` (IntelligenceEvent) and `intelligence.i7.signals`
- **AI Narrative:** `indicagent-ai-narrative` (`ai_narrative_agent.py`) runs I8 via Ollama; publishes to `narratives` topic
- **Distribution:** Redpanda (Kafka-compatible) distributes intelligence across all tiers
- **Persistence:** Dedicated WriterAgents (`indicagent-feature-writer`, `indicagent-signal-writer`, `indicagent-llm-writer`) consume from topics and write to TimescaleDB

---

## **Intelligence Development Status**

### **Completed Tiers (Production Ready)**

| Tier | Plugins | Notes |
|------|---------|-------|
| I1 Technical Indicators | 27 | RSI, MACD, MA/EMA, MACompare, Bollinger, ATR, Stochastic, CCI, Williams %R, MFI, OBV, VWAP, Supertrend, PSAR, StochRSI, CMF, Aroon, ChandelierExit, HistoricalVolatility, ROC/PPO, ADX, Keltner, Donchian, ACOscillator, HMA, OFI, CVD — all incremental `compute_next()` |
| I2 Composite Events | 10 | RSIEvents, StochasticEvents, ADXEvents, VolumeEvents, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore, AccelerationRegime |
| I3 Market Structure | 8 | MACDEvents, SwingDetector, SupportResistance, TrendStructure, MarketProfile, SessionLevels, FibonacciZones, SwingMomentum |
| I4 Context / Regime | 12 | VolatilityRegime, TrendRegime, MomentumContext, GARCHVolatility, HurstExponent, ShannonEntropy, KalmanTrend, SessionContext, AnchoredVWAP, VolumeProfile, VIXRegime, CrossAssetContext |
| I5 Patterns | 16 | MTFVolatility, RSIDivergence, BollingerSqueeze, VolumeDivergence, MACDDivergence, CMFDivergence, Confluence, TrendConfluence, DoubleTopBottom, HeadShoulders, TriangleWedge, CandlestickPatterns, FlagPennant, CupHandle, MeasuredMove, KeyLevelReaction |
| SMC | 13 | BOS/CHoCH, FairValueGap, OrderBlocks, LiquiditySweeps, BOCPDChangepoint, HMMRegime, LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount |
| I6 Confluence | 1 | CrossTimeframeConfluence — recency-weighted multi-TF alignment, 10 output fields |
| I7 Trading Setups | 36 + 2 agg | 36 setup plugins + CISScorer aggregator + SignalAggregator |
| I8 AI Narrative | 1 service | `ai_narrative_agent` — OpenRouter primary → Ollama gemma4:e4b fallback; reads `intelligence.journal` |

### **Totals**
- **123 registered plugins + 2 aggregation components:** 27 I1 + 10 I2 + 8 I3 + 12 I4 + 16 I5 + 13 SMC + 1 I6 + 36 I7

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