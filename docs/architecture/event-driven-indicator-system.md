# Plugin-Native Intelligence Processing Architecture

**Version:** 5.0.0
**Last Updated:** 2026-03-11
**Status:** I1-I8 pipeline complete — 95 plugins + 2 aggregation components + feature store + typed intelligence bus, 1497 passing

## Executive Summary

IndicAgent's plugin-native intelligence processing system transforms live market data into sophisticated intelligence through event-driven, stream-based processing. The system implements a complete I1-I8 intelligence framework using plugin-based DAG execution, real-time DragonflyDB stream processing, and a typed intelligence bus that carries all tier outputs from raw features through AI synthesis.

**Core Capability:** Real-time intelligence generation across 95 plugins spanning 8 tiers — from mathematical indicators through smart money concepts, confluence scoring, trading setups, and LLM-powered market narratives. 1497 passing tests. 24 active contracts.

---

## **Plugin-Native Intelligence Architecture**

### **Event-Driven Intelligence Processing**

The pipeline is fully service-native: each tier runs in a dedicated systemd service consuming upstream Redis streams and publishing to downstream streams. There is no LangGraph workflow layer — orchestration is handled by the stream topology itself.

#### **Core Intelligence Files**
- `src/intelligence/register_plugins.py` — `TIER_I1`…`TIER_I7` lists, single source of truth for plugin registration
- `src/intelligence/schemas.py` — `IntelligenceEvent` Pydantic model (canonical typed bus schema)
- `src/intelligence/plugins.py` — `IndicatorPlugin` and `PatternPlugin` protocols
- `src/intelligence/dag.py` — DAG execution engine with dependency resolution

#### **Stream Infrastructure**
- `src/core/stream_keys.py` — all stream key construction (env-prefixed)
- `src/core/stream_utils.py` — `ensure_consumer_group_with_reset()` and consumer group helpers
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, 24 active contracts

#### **Service Orchestration**
- `services/indicator_service.py` — I1+I2 pipeline
- `services/market_analysis_service.py` — I3→I4→I5→SMC→I6 pipeline
- `services/signal_generator_service.py` — I7 setup detection + aggregation
- `services/signal_lifecycle_service.py` — signal zone tracking, MAE/MFE, 8-class outcome
- `services/ai_narrative_service.py` — I8 LLM narrative generation
- `services/feature_writer_service.py` — Redis → TimescaleDB batch writer
- `services/llm_writer_service.py` — LLM call audit + outcome back-fill + score cache
- `src/api/main.py` — FastAPI + SSE on :8000
- `production/daemons/high_frequency_tws_daemon.py` — IBKR tick + bar collection with built-in multi-TF aggregation

---

## **Real-Time Intelligence Pipeline**

```
IBKR TWS → indicator_service (I1+I2) → market_analysis_service (I3→I4→I5→SMC→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard

signal_lifecycle_service reads market:{symbol}:1m independently
ai_narrative_service reads signals:{symbol}:{tf}:aggregated
llm_writer_service reads llm_calls:stream
```

### **Processing Stages**

1. **Market Data** — `indicagent-tws` collects IBKR ticks + bars, aggregates multi-TF bars, publishes to `market:{symbol}:{tf}` and `ticks:{symbol}:live`
2. **I1+I2 Features** — `indicagent-indicator` reads market bars, runs 25 I1 indicator plugins + 10 I2 composite/derivative plugins per symbol/TF, publishes to `indicators:{symbol}:{tf}`
3. **I3→I6 Analysis** — `indicagent-market-analysis` reads indicator stream, runs I3→I4→I5→SMC→I6 in sequence, publishes typed `IntelligenceEvent` to `intelligence:{symbol}:{tf}`
4. **I7 Setups** — `indicagent-signal-generator` reads intelligence stream, runs 17 setup plugins + CISScorer + SignalAggregator, writes to `signals:{symbol}:{tf}:aggregated` and `signal_ledger`
5. **I8 Narrative** — `indicagent-ai-narrative` reads aggregated signals, calls Ollama LLM, publishes to `narratives:{symbol}:{tf}`
6. **Persistence** — `indicagent-feature-writer` batch-writes `intelligence:{symbol}:{tf}` events to `intelligence_features` hypertable
7. **LLM Audit** — `indicagent-llm-writer` persists every LLM call from `llm_calls:stream` to `llm_calls` hypertable and back-fills outcomes

---

## **I1-I8 Intelligence Tiers**

### **I1 — Raw Technical Indicators (25 plugins)**

Incremental `compute_next()` calculations with <1ms per plugin per bar.

Plugins: RSI, MA/EMA, MACompare, MACD, ATR, BollingerBands, Stochastic, CCI, WilliamsR, MFI, OBV, VWAP, Supertrend, ADX/DMI, Keltner, Donchian, ROC/PPO, Aroon, ChandelierExit, CMF, HistoricalVolatility, PSAR, StochRSI, ACOscillator, HMA

**Output stream:** `indicators:{symbol}:{tf}`

### **I2 — Composite Indicators / Second Derivatives (10 plugins)**

Plugins: MACD Events, RSI Events, Stoch Events, ADX Events, Volume Events, MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore/AccelRegime

**Output stream:** `indicators:{symbol}:{tf}` (same stream as I1, tiered within payload)

### **I3 — Market Structure (8 plugins)**

Plugins: Swing, SR, Trend, MarketProfile, SessionLevels, AnchoredVWAP, FibZones, SwingMomentum

### **I4 — Context / Regime Classification (7 plugins)**

Plugins: VolRegime, TrendRegime, MomentumCtx, GARCHVol, KalmanTrend, SessionCtx, MTFVol

### **I5 — Pattern Recognition (14 plugins)**

Plugins: RSIDivergence, BollingerSqueeze, VolDivergence, Confluence, TrendConfluence, DoubleTB, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle, MeasuredMove, VolumeProfile, KeyLevelReaction

### **SMC — Smart Money Concepts (13 plugins)**

Plugins: BOS/CHoCH, FVG, OrderBlocks, LiquiditySweeps, BOCPD, HMM, LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount

### **I6 — Cross-Timeframe Confluence (1 plugin)**

Plugin: CrossTimeframeConfluence — aggregates I3/I4/I5/SMC signals across timeframes into a unified confluence score.

**Output stream:** `intelligence:{symbol}:{tf}` (typed `IntelligenceEvent`)

### **I7 — Trading Setups + Aggregation (17 setup plugins + 2 aggregation components)**

Setup plugins: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysis, CandlestickPatternSetup, SessionExtremes

Aggregation components:
- **CISScorer** — Confluence Intelligence Score, weights setup signals by regime, performance, and setup type
- **SignalAggregator** — selects the highest-ranked eligible signal, applies `perf_multiplier` from `setup_performance` table (gated at N≥30 samples)

**Output stream:** `signals:{symbol}:{tf}:aggregated` — `direction=0` marks terminal/resolved events

**Warmup note:** signal_generator_service needs ~50 live 1m bars (~50 min) after restart before signals fire. Consumer group is not rewound on restart — natural warmup is expected behavior.

### **I8 — AI Narrative (Ollama LLM)**

- Per-signal analysis: `qwen3.5:9b`
- Group synthesis: `phi4-mini:3.8b`
- Every LLM call (success, failure, counterfactual) published to `llm_calls:stream` (maxlen=500)
- Outcomes back-filled via `llm_outcomes:stream` (maxlen=200)

**Output stream:** `narratives:{symbol}:{tf}`

---

## **Typed Intelligence Bus**

All I3-I6 outputs travel as `IntelligenceEvent` (defined in `src/intelligence/schemas.py`):

| Field | Type | Description |
|-------|------|-------------|
| `ts` | datetime | Bar timestamp |
| `symbol` | str | Instrument symbol |
| `tf` | str | Timeframe (1m, 5m, 15m, 1h, 1d) |
| `bar` | dict | OHLCV data |
| `i1` | dict | I1 indicator outputs |
| `i3` | dict | I3 market structure outputs |
| `i4` | dict | I4 context/regime outputs |
| `i5` | dict | I5 pattern recognition outputs |
| `smc` | dict | SMC outputs |
| `i6` | dict | I6 confluence outputs |

Persisted to `intelligence_features` hypertable as tiered JSONB columns (bar/i1/i3/i4/i5/smc/i6) by `feature_writer_service`.

---

## **Stream Architecture**

All stream keys are env-prefixed (`development:` in dev, no prefix in production) and constructed exclusively via `src/core/stream_keys.py`.

```yaml
market:{symbol}:{tf}               # OHLCV bars (all timeframes)
ticks:{symbol}:live                # Raw IBKR ticks
indicators:{symbol}:{tf}           # I1+I2 outputs
intelligence:{symbol}:{tf}         # Typed IntelligenceEvent (I3-I6)
signals:{symbol}:{tf}:aggregated   # I7 selected setup (direction=0 = terminal)
narratives:{symbol}:{tf}           # I8 AI narrative
llm_calls:stream                   # Every LLM call (maxlen=500)
llm_outcomes:stream                # Signal lifecycle exits (maxlen=200)
```

**Consumer groups:** Use `ensure_consumer_group_with_reset()` from `src/core/stream_utils`. Gotcha: `xgroup_create(..., "$")` silently fails when group already exists — the `except` block must call `xgroup_setid(stream, group, "$")` to force-reset to current position.

---

## **Services Reference**

| Service | Unit | Source | Metrics |
|---------|------|--------|---------|
| TWS Daemon | `indicagent-tws` | `production/daemons/high_frequency_tws_daemon.py` | — |
| Indicator | `indicagent-indicator` | `services/indicator_service.py` | :9109 |
| Market Analysis | `indicagent-market-analysis` | `services/market_analysis_service.py` | :9114 |
| Signal Generator | `indicagent-signal-generator` | `services/signal_generator_service.py` | :9112 |
| Signal Lifecycle | `indicagent-signal-lifecycle` | `services/signal_lifecycle_service.py` | :9115 |
| AI Narrative | `indicagent-ai-narrative` | `services/ai_narrative_service.py` | :9113 |
| Feature Writer | `indicagent-feature-writer` | `services/feature_writer_service.py` | :9116 |
| LLM Writer | `indicagent-llm-writer` | `services/llm_writer_service.py` | :9117 |
| API | `indicagent-api` | `src/api/main:app` | :8000 |

All services are systemd-managed with `Restart=always`. Logs: `journalctl -u indicagent-<name> -f`.

---

## **Data Persistence (Cold Tier)**

### **TimescaleDB Tables**

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV — backfill only, ground truth | Forever |
| `intelligence_features` | Full feature vectors per bar including i7/i8 JSONB — ML training dataset | Forever |
| `signal_ledger` | I7 signals + lifecycle outcomes; JOIN via `(symbol, feature_ts, feature_tf)` | Forever |
| `llm_calls` | Full LLM audit log per call; outcome back-filled by `llm_writer_service` | Forever |
| `llm_model_scores` | Per-model win rate / avg pnl_r / p-value; refreshed every 15 min | — |
| `setup_performance` | Per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); N≥30 gate | — |

### **Hot/Warm/Cold Tiers**

```
Hot:  IBKR TWS → DragonflyDB Streams → Services          (<1ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```

The real-time pipeline never touches the database directly.

---

## **Performance**

- **Plugin calculation:** <1ms per plugin incremental (141x vs batch recalculation)
- **Tick throughput:** 100–500+ ticks/second during RTH
- **Consumer group polling:** Single `xreadgroup` across all streams (not sequential) to avoid worst-case lag
- **Test coverage:** 1497 passing unit tests

---

## **Current Status (v1.7, 2026-03-11)**

- **95 registered plugins** across I1–I7 (25+10+8+7+14+13+1+17)
- **2 aggregation components** (CISScorer, SignalAggregator)
- **I1→I2→I3→I4→I5→SMC→I6→I7→I8** fully wired end-to-end
- **Feature store** operational — `intelligence_features` hypertable populated by `feature_writer_service`
- **Signal lifecycle** — zone-aware activation, MAE/MFE tracking, 8-class outcome classification
- **LLM audit** — every call logged; model score cache updated every 15 min
- **24 active contracts** via `get_active_contracts()` in `src/config/settings.py`
- **1497 passing tests**

---

**Related Documentation:**
- [Layered Architecture](layered-architecture.md) — Complete system architecture overview
- [Intelligence Tiers](../concepts/intelligence-tiers.md) — I1-I8 intelligence processing framework
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) — Advanced intelligence processing
