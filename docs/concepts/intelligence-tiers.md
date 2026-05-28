<!-- generated-by: gsd-doc-writer -->
# Intelligence Engine Tiers (I1–I8)

**Version:** 2.8
**Status:** current
**Current State:** 132 plugins + 2 aggregation components — source of truth: `src/intelligence/register_plugins.py` TIER_* lists
**Last Updated:** 2026-05-27
**Documentation Style:** Dual tier/functional naming (see [Tier Naming System](tier-naming-system.md))

## Overview

The Intelligence Engine implements progressive intelligence extraction through eight specialized tiers (I1-I8), each building upon previous tiers to transform raw market data into sophisticated, actionable intelligence. This framework provides the foundation for IndicAgent's market intelligence platform.

**Architecture Philosophy:** Progressive intelligence refinement from mathematical features to AI-powered market insights.

**Naming Convention:** This documentation uses both tier codes and functional names for clarity:
- **I1: Technical Indicators** (`technical_indicators`) - Mathematical features
- **I7: Trading Signals** (`trading_signals`) - Setup generation

See [Tier Naming System](tier-naming-system.md) for complete mapping and usage guidelines.

---

## **Intelligence Tier Framework**

### **Mathematical Intelligence Foundation (I1-I4)**

#### **I1: Technical Indicators (`technical_indicators`)**
**Purpose:** Extract mathematical features from raw market data
**Intelligence Focus:** Foundation mathematical analysis of price, volume, momentum, volatility

- **Input:** OHLCV bars
- **Output:** `technical_indicators` JSONB field (raw mathematical values: `sma_20`, `ema_21`, `rsi_14`, `atr_14`)
- **Code Location:** `src/intelligence/features/i1_indicators/`
- **Examples:** RSI, MACD, SMA/EMA, Bollinger Bands, ATR, Stochastic, CCI, Williams %R, MFI, OBV, OFI, CVD, VolumeZscore

#### **I2: Composite Events (`composite_events`)**
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
- **Code Location:** `src/intelligence/features/i3_structure/`
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
- **Code Location:** `src/intelligence/features/i5_patterns/`
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
- **Code Location:** `src/intelligence/features/smc_context/`
- **Plugins (16):** Four HMM instances (1m/5m/15m/1h) count as separate plugins
  - `BOS_CHoCH` — break of structure and change of character detection
  - `FairValueGap` — bullish/bearish FVG detection with fill tracking
  - `OrderBlocks` — bullish/bearish order block identification
  - `LiquiditySweeps` — sweep of buyside/sellside liquidity with reclaim confirmation
  - `BOCPDChangepoint` — Bayesian online changepoint detection for regime shifts
  - `HMMRegime (1m)` — Hidden Markov Model per timeframe: ranging(0) / trending(1/2) with probability
  - `HMMRegime (5m)` — HMM instance for 5m timeframe
  - `HMMRegime (15m)` — HMM instance for 15m timeframe
  - `HMMRegime (1h)` — HMM instance for 1h timeframe
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
- **Plugins (6):**
  - `CrossTimeframeConfluence` — recency-weighted alignment of trend / structure / regime / pattern / I2 events / SMC BOS sub-score across timeframes; 10 output fields
  - `CrossTimeframeMomentumDivergence` — momentum divergence across timeframes
  - `CrossTimeframeSRConfluence` — S/R level confluence across timeframes
  - `CrossTimeframeRegimeAgreement` — regime agreement scoring across timeframes
  - `SqueezeExpansionDivergence` — squeeze/expansion divergence across timeframes
  - `CrossTimeframeOrderflowAlignment` — orderflow alignment across timeframes

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
  - *Volume profile (+6):* `VCP`, `AnchoredVWAPReversion`, `VWAPReclaim`, `POCRejection`, `HVNRejection`, `LVNBreakout`
  - *Microstructure (+7):* `OFIContinuation`, `OFIDivergence`, `OFISpike`, `CVDDivergence`, `CVDSpike`, `DeltaExhaustion`, `DualDivergence`
  - *Cross-asset (+1):* `CrossAssetDivergence`
  - **Quality gates:** GARCH/Kalman checks on `MeanReversion`, `VWAPDeviation`, `SqueezeExpansion`
  - **`regime_type` required** on all I7 plugins: `"trend"` | `"mean_reversion"` | `"any"` — used by the regime gate
- **Signal Aggregation (CISScorer):**
  - 6-bucket weighted scorer: trend / momentum / structure / pattern / institutional / regime
  - **Regime eligibility filter:** trend plugins → trending regime only (HMM 1/2); mean-reversion plugins → ranging regime only (HMM 0); gate bypassed when `hmm_regime_prob < REGIME_PROB_MIN` (settings-configurable, default 0.30) or `hmm_regime_duration < REGIME_DUR_MIN` (default 1 bar)
  - **Setup performance multiplier:** Sharpe-ranked weights loaded from `signal_metrics` table at startup and every hour; governs which setup plugin wins when multiple eligible signals fire (see [CIS Scoring](cis-scoring.md))

---

### **AI Intelligence Synthesis (I8)**

#### **I8: AI Narrative Synthesis**
**Purpose:** Convert I7 signals into human-readable market narratives via LLM
**Intelligence Focus:** Natural language market analysis, per-signal + asset-group synthesis

- **Input:** High-confidence I7 signals from `intelligence.journal` topic
- **Output:** Narrative text published to `narratives` Kafka topic (keyed `SYMBOL:TF`)
- **Service:** `services/ai_narrative_agent.py` (systemd: `indicagent-ai-narrative`)
- **Topics:**
  - `narratives` (keyed `SYMBOL:TF`) — per-signal narrative
  - `narratives.group` — 6-asset-group synthesis (equity/energy/metals/rates/fx/crypto)
- **LLM Provider:** Single provider — Ollama Local (gemma4:e4b default; `.env` may override via `OLLAMA_MODEL`). OpenRouter, DeepSeek, OllamaCloud providers removed. Timeout: 60s.
- **Audit:** Every LLM call published to `llm.calls` → `indicagent-llm-writer` persists to `llm_calls` hypertable
- **Lineage:** `LineageRecorder` tracks prompt version, model, inputs, outputs, and timing per call

### **AI Swarm Overlay**

Beyond I8 narratives, the AI layer includes a swarm of specialist agents that evaluate signal quality:

- **Service:** `AlphaSwarmComputeAgent` dispatches 5 specialist agents per signal
- **Agents (5 total):**
  - `skeptic_v1` — counterfactual challenge (120s LLM budget)
  - `correlation_v1` — independence check (120s LLM budget)
  - `regime_coherence_v1` — regime consistency (120s LLM budget)
  - `counterfactual_v1` — historical pattern (120s LLM budget)
  - `ml_scorer_v1` — local LightGBM scorer (50ms, no LLM call)
- **Output:** `swarm_multiplier` (range-clamped `[0.0, 2.0]`) applied to `adjusted_confidence`
- **Weight learning:** Per-agent Spearman correlation with signal outcomes, 30-day rolling window
- **Shadow governance:** All agents start in shadow mode; promotion gated by statistical significance
- **See:** [Swarm Intelligence](swarm-intelligence.md)

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

**Canonical event model:** `IntelligenceEvent` in `src/intelligence/schemas.py` — tiered JSONB (`i1`, `i3`, `i4`, `i5`, `smc`, `i6`), versioned.

---

## **Processing Architecture**

### **Execution Model**

All I1–I7 tiers execute within `IntelligencePipelineComputeAgent` as a unified in-process pipeline (`services/intelligence_pipeline_agent.py`, systemd: `indicagent-intelligence-pipeline`). Kafka and TimescaleDB are output sinks only — no inter-tier messaging.

**Pipeline capacity:** Sequential bar processing (`await _process_bar`). Per-bar latency measured by `intelligence_pipeline_pipeline_latency_ms` gauge. 132 plugins across 6 stages, 12 thread-pool workers.

---

## **Code Organization**

```
src/intelligence/
├── features/
│   ├── i1_indicators/    # I1 technical indicator plugins
│   ├── i3_structure/     # I3 market structure plugins
│   ├── i5_patterns/      # I5 pattern recognition plugins
│   └── smc_context/      # I6 SMC plugins
├── composites/           # I2 composite event plugins
├── context/              # I4 regime and context plugins
├── confluence/           # I6 cross-timeframe confluence plugins
└── trading/              # I7 setup plugins, CISScorer, aggregator, shared utilities
```

Plugin names use short descriptive `PascalCase` matching the class name. I4 context plugins are prefixed `ctx_` in the registry (e.g., `ctx_AnchoredVWAP`), I7 setup plugins use `trad_` (e.g., `trad_TrendFollowing`). See `src/intelligence/register_plugins.py` for canonical names.

---

## **Intelligence Development Status**

### **Completed Tiers (Production Ready)**

| Tier | Plugins | Notes |
|------|---------|-------|
| I1 Technical Indicators | 28 | RSI, MACD, MA/EMA, MACompare, Bollinger, ATR, Stochastic, CCI, Williams %R, MFI, OBV, VWAP, Supertrend, PSAR, StochRSI, CMF, Aroon, ChandelierExit, HistoricalVolatility, ROC/PPO, ADX, Keltner, Donchian, ACOscillator, HMA, OFI, CVD, VolumeZscore — all incremental `compute_next()` |
| I2 Composite Events | 10 | RSIEvents, StochasticEvents, ADXEvents, VolumeEvents, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore, AccelerationRegime |
| I3 Market Structure | 8 | MACDEvents, SwingDetector, SupportResistance, TrendStructure, MarketProfile, SessionLevels, FibonacciZones, SwingMomentum |
| I4 Context / Regime | 12 | VolatilityRegime, TrendRegime, MomentumContext, GARCHVolatility, HurstExponent, ShannonEntropy, KalmanTrend, SessionContext, AnchoredVWAP, VolumeProfile, VIXRegime, CrossAssetContext |
| I5 Patterns | 16 | MTFVolatility, RSIDivergence, BollingerSqueeze, VolumeDivergence, MACDDivergence, CMFDivergence, Confluence, TrendConfluence, DoubleTopBottom, HeadShoulders, TriangleWedge, CandlestickPatterns, FlagPennant, CupHandle, MeasuredMove, KeyLevelReaction |
| SMC | 16 | BOS/CHoCH, FairValueGap, OrderBlocks, LiquiditySweeps, BOCPDChangepoint, HMMRegime×4 (1m/5m/15m/1h), LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount |
| I6 Confluence | 6 | CrossTimeframeConfluence, CrossTimeframeMomentumDivergence, CrossTimeframeSRConfluence, CrossTimeframeRegimeAgreement, SqueezeExpansionDivergence, CrossTimeframeOrderflowAlignment |
| I7 Trading Setups | 36 + 2 agg | 36 setup plugins + CISScorer aggregator + SignalAggregator |
| I8 AI Narrative | 1 service | `ai_narrative_agent` — Ollama Local (gemma4:e4b default); reads `intelligence.journal` |

### **Totals**
- **132 registered plugins + 2 aggregation components:** 28 I1 + 10 I2 + 8 I3 + 12 I4 + 16 I5 + 16 SMC + 6 I6 + 36 I7

---

**Related Documentation:**
- [Plugin Architecture](plugin-architecture.md) — plugin protocol, registry, incremental compute
- [DAG Execution](dag-execution.md) — how plugin dependencies are ordered
- [CIS Scoring](cis-scoring.md) — I7 signal aggregation and regime gating
- [Signal Lifecycle](signal-lifecycle.md) — what happens after I7 fires a signal
