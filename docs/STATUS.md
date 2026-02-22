# IndicAgent Platform Status

> **Last Updated:** 2026-02-22
> **Version:** 4.9.2
> **Phase:** I7 Phase 0 complete — 57 plugins, 551 tests

---

## Current State Summary

**Infrastructure:** Production-ready
**Intelligence Pipeline:** Fully operational (I1 → I8)
**Test Coverage:** 551 unit tests passing, 0 lint errors
**Data Collection:** Active (ES, NQ, RTY + 11 more contracts)

---

## System Health

| Component | Status | Health Endpoint |
|-----------|--------|-----------------|
| HF TWS Daemon | RUNNING | N/A |
| Indicator Processor | RUNNING | :9109/health |
| Enhanced Processor | RUNNING | :9109/health |
| Timeframe Builder | RUNNING | :9110/health |
| Intelligence Processor | RUNNING | N/A |
| Signal Orchestrator | RUNNING | :9112/health |
| AI Narrative Service | RUNNING | :9113/health |
| Backend API | RUNNING | :8000/health |
| Dashboard | RUNNING | http://localhost:3000 |

---

## Intelligence Tiers

| Tier | Name | Plugins | Status |
|------|------|---------|--------|
| I1 | Technical Indicators | 23 | COMPLETE (6 new in v4.7.0) |
| I2 | Composite Indicators | — | COMPLETE (built-in: crossovers, slopes) |
| I3 | Market Structure | 3 | COMPLETE |
| I4 | Context Classification | 5 | COMPLETE |
| I5 | Pattern Detection | 8 | COMPLETE |
| I6 | Smart Money Concepts | 8 | COMPLETE (2 new in v4.9.1: LiqPools, S/D Zones) |
| I6 | Cross-Timeframe Confluence | 1 | COMPLETE |
| I7 | Trading Setups | 9 | PHASE_2_IN_PROGRESS (4 added since v4.8.0) |
| I7 | Signal Aggregation | 4 components | RUNNING |
| I8 | AI Intelligence | 1 service | WORKING |

**Total Plugins:** 57 registered (23 indicators + 34 patterns)

### Known Issues

None.

---

## Development Priorities

### Priority 1: I7 Phase 2 — More Setup Plugins
**Continue expanding signal coverage (7 of 14 target plugins remaining)**

- Supply/Demand Zone Setup (fully designed — `docs/plans/2026-02-22-liquidity-pools-supply-demand-design.md`)
- Gap Analysis Setup (session open trades)
- See `docs/roadmap/MASTER_ROADMAP.md` Phase 4 for full list

### Priority 2: ML Scoring Model Calibration
**Replace rules-based aggregator with a calibrated scoring model**

- Requires 500+ signals in `signal_ledger` with P&L outcomes (~17 days of collection)
- XGBoost/LightGBM on 15 extracted features → pnl_r continuous target
- A/B test rules vs scored aggregator in parallel
- See `docs/roadmap/MASTER_ROADMAP.md` Phase 3 for full spec

---

## Completed Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **LG-1** | LangGraph event-driven workflows, circuit breakers | Complete |
| **CQ-1** | Code quality: 1,323 lint fixes, formatting | Complete |
| **PR-2** | Production: test runner, incremental_manager, parallel services, SSE | Complete |
| **PI-1** | 16 indicator plugins with hybrid processing | Complete |
| **T2** | Tier 2 refactor: calculations.py + redis_streams_manager.py split into mixins | Complete |
| **I3** | Market structure: 3 plugins (swing detector, support/resistance, trend structure) | Complete |
| **I4** | Context classification: 5 plugins (volatility regime, trend regime, momentum context, GARCH vol, Kalman trend) | Complete |
| **I5** | Pattern detection: 5 plugins (RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence, trend confluence) | Complete |
| **FH** | Foundation hardening: shared utils, temporal metadata, continuous scores | Complete |
| **SMC** | Smart money concepts: 6 plugins (BOS/CHoCH, FVG, OB, liq sweeps, BOCPD, HMM) | Complete |
| **I6** | Cross-timeframe confluence: trend/structure/regime/pattern alignment scoring | Complete |
| **Cleanup** | ~7,500 lines dead code removed across four rounds (incl. langgraph_event_processor) | Complete |
| **Deps** | Full dependency upgrade (pandas 3.0, redis 7.1, LangGraph 1.0, etc.) | Complete |
| **I1-ext** | Supertrend indicator + GARCH(1,1) volatility forecast + TrendConfluence pattern | Complete |
| **I7-P1** | I7 Phase 1: 5 trading setup plugins | Complete |
| **I7-P1.5** | I7 Phase 1.5: signal aggregation components (ledger, aggregator, lifecycle, sizer) | Complete |
| **I7-Orch** | Signal Orchestrator Service: live signal collection running (port 9112) | Complete |
| **DataEff** | Data collection efficiency: provisional bars at :00, authoritative correction at :05 | Complete |
| **I8** | AI Narrative Service: Ollama qwen3:8b narratives from aggregated signals (port 9113) | Complete |
| **I4-Kalman** | ctx_KalmanTrend: 1D Kalman filter, 7 outputs, optional GARCH-adaptive R, 9 tests | Complete |
| **I5-ChartPatt** | Chart patterns: patt_DoubleTB, patt_HeadShoulders, patt_TriangleWedge (17 tests) | Complete |
| **DataLayer** | DataProvider protocol, IBKRProvider, Instrument model, TimescaleDB 5m/15m caggs (migration 008) | Complete |
| **PluginRegistry** | TIER_* constants in register_plugins.py (single source of truth); validate_tier() hard-crashes on bad names | Complete |

---

## Data Infrastructure

**Hot Tier:** DragonflyDB (Redis protocol) — <1ms latency
**Warm Tier:** Redis Streams — Real-time processing
**Cold Tier:** TimescaleDB — Historical analysis

**Stream Keys:**
- Market data: `market:SYMBOL:TIMEFRAME`
- Indicators: `indicators:SYMBOL:TIMEFRAME`
- Intelligence: `intelligence:SYMBOL:TIMEFRAME`
- Signals: `signals:SYMBOL:TIMEFRAME:aggregated`
- Narratives: `narratives:SYMBOL:TIMEFRAME`

See [Stream Schemas](reference/schemas/stream-schemas.md) for details.

---

## Instrumentation

**Active Contracts:** 14 futures
- **Equity Indices:** ES, NQ, RTY
- **Energy:** CL, NG
- **Metals:** GC, SI, HG, PL
- **Rates:** ZN, ZF, ZB, ZT
- **Volatility:** VX

**Timeframes:** 1m, 5m, 15m, 1h, 4h, 1d

---

## Development Environment

**Python:** 3.13
**Key Dependencies:** pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0
**Infrastructure:** Docker (TimescaleDB, DragonflyDB, Ollama)
**Frontend:** Next.js 15.5, React 19

**Local LLMs (Ollama):** Available at http://localhost:11434
- **Default:** `qwen3:8b` (5.2 GB, thinking mode)
- See [Intelligence Tiers](concepts/intelligence-tiers.md#i8) for full model list

---

## Architecture Quick Reference

**Plugin Totals:** 57 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 8 SMC + 1 I6 + 9 I7) | 551 unit tests
**Services:** hf-tws-daemon, indicator-processor, enhanced-processor, timeframe-builder, intelligence-processor, signal-orchestrator (:9112), ai-narrative (:9113)
**Stack:** Python 3.13, FastAPI 0.129, Redis 7.1/DragonflyDB, TimescaleDB, LangGraph 1.0, Ollama
**Dashboard:** Next.js 15.5 / React 19 / Tailwind v4

**Detailed Architecture:** [CLAUDE.md](for-ai-assistants/CLAUDE.md)
**Intelligence Tiers:** [docs/architecture/intelligence-tiers.md](architecture/intelligence-tiers.md)
**Plugin Framework:** [docs/architecture/plugin-registry-and-dag-execution.md](architecture/plugin-registry-and-dag-execution.md)
**Roadmap:** [docs/roadmap/MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md)

---

## Recent Changes

### 2026-02-22 (v4.9.2)
- FEAT I7 Phase 0 — GARCH/Kalman quality gates wired into 3 plugins:
  - `trad_MeanReversion`: gate on `abs(kalman_price_position) < 1.0σ` (price too near Kalman fair value → no signal)
  - `trad_VWAPDeviation`: dynamic sigma threshold via `garch_vol_regime` (0/1: 2.0σ, 2: 2.5σ, 3: 3.0σ)
  - `trad_SqueezeExpansion`: hard block when `garch_vol_regime == 3` (extreme vol, top 5th percentile)
- TEST +9 tests (542 → 551 unit tests total)

### 2026-02-22 (v4.9.1)
- REFACTOR Plugin tier lists consolidated into `TIER_*` constants in `register_plugins.py` (single source of truth)
- ADD `PluginRegistry.validate_tier()` — hard crash at service startup on unknown plugin names (no more silent skips)
- FIX All 5 service files import tier constants; hardcoded string lists eliminated
- FIX Plugin gaps wired: smc_LiquidityPools, smc_SupplyDemandZones added to TIER_SMC; trad_LiquidityHunt, trad_SupplyDemandSetup added to TIER_I7
- FIX Prior session gaps: ctx_KalmanTrend, patt_DoubleTB/HeadShoulders/TriangleWedge, smc_HMMRegime, MAComposite, ADX, Keltner, Donchian wired in both service files
- TEST +49 tests (493 → 542 total)

### 2026-02-22 (v4.9.0)
- COMPLETE Data Layer Redesign: `DataProvider` protocol, `IBKRProvider` (all ib_insync isolated), `Instrument`+`AssetClass` models, `IBKRContract` deprecated alias
- DELETE `IBKRFetcher`, `aggregate_1m_to_tf()`, `time_bucket()` from historical_backfill.py
- ADD TimescaleDB continuous aggregates: `market_data_5m`, `market_data_15m` (migration 008)
- TEST +40 tests (453 → 493 total, 17 new provider tests)

### 2026-02-20 (v4.8.0)
- COMPLETE I7 Phase 2: trad_VWAPDeviation (VWAP mean-reversion, 2σ gate) + trad_MomentumBreakout (triple-gate: ROC+vol+structure)
- ADD ROC_PPO to I1_PLUGINS — roc_14 now available in features dict for all downstream plugins
- COMPLETE Dashboard Signal/Narrative Panel — SignalPanel (per-symbol) + NarrativePanel (global AI feed) wired to SSE
- TEST +16 tests (437 → 453 total)
- KNOWN ISSUE: Track A I1 indicators registered but not in I1_PLUGINS (see Known Issues above)

### 2026-02-20 (v4.7.0)
- COMPLETE Track A: 6 new I1 indicators — ind_ParabolicSAR, ind_StochRSI, ind_CMF, ind_Aroon, ind_ChandelierExit, ind_HistoricalVolatility
- TEST +54 tests (383 → 437 total)

### 2026-02-19 (v4.6.0)
- COMPLETE I5 chart pattern plugins: patt_DoubleTB, patt_HeadShoulders, patt_TriangleWedge
- ADD two-stage swing filter, sloped H&S neckline, convergence-ratio triangle confidence
- REMOVE 883-line langgraph_event_processor.py (dead code — replaced by plugin DAG)
- TEST +3 tests (380 → 383 total)

### 2026-02-19 (v4.5.0)
- COMPLETE ctx_KalmanTrend: 1D local-level Kalman filter, 7 outputs, GARCH-adaptive R option
- TEST +9 tests (371 → 380)

### 2026-02-19 (v4.4.0)
- COMPLETE I8 AI Narrative Service: Ollama qwen3:8b narratives from `signals:aggregated`
- COMPLETE Data Collection Efficiency: provisional bars (tick_derived at :00) + authoritative correction (histData at :05)
- ADD `narratives:SYMBOL:TF` stream (maxlen=100) + `narrative:SYMBOL:TF:latest` hash cache (90s TTL)
- ADD `source` field to bar messages: `tick_derived` vs `authoritative`
- ADD xack-in-finally PEL safety pattern to AINarrativeService and SignalOrchestrator
- TEST +48 new unit tests (309 → 357)

### 2026-02-18 (v4.3.0)
- FIX `is_num` NaN/Inf vulnerability (math.isfinite guard)
- FIX VWAP session reset on date boundary + add SD bands (±1σ, ±2σ)
- FIX TrendRegime consumes upstream sma_20/sma_50 from features
- PERF Vectorize find_peaks/find_troughs with numpy (~50-100x speedup)
- REFACTOR ADX deduplication — single-pass computation (remove _seed_state)
- ADD Supertrend indicator (ATR-based binary trend direction, I1)
- ADD GARCH(1,1) volatility forecast (conditional vol + regime, I4)
- ADD TrendConfluence pattern (6-signal trend aggregation, I5)
- TEST +51 new unit tests (258 → 309)

### 2026-02-17 (v4.2.0)
- COMPLETE I7 Phase 1.5: Signal aggregation components (aggregator, ledger, lifecycle, sizer)
- ADD 45 new tests for signal aggregation

### 2026-02-16 (v4.1.0)
- COMPLETE I7 Phase 1: 5 trading setup plugins
- ADD signal.v1 schema with SSE wiring

### 2026-02-15 (v4.0.0)
- COMPLETE I6 Smart Money: BOCPD changepoint + HMM regime classification
- ADD Cross-timeframe confluence plugin
