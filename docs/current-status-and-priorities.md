# IndicAgent - Current Status & Development Priorities

**Version:** 4.5.0
**Last Updated:** 2026-02-19
**Status:** I1-I8 Complete, 42 Plugins, 366 Tests Passing

## Current Status: Full Intelligence Pipeline Operational

### Completed Work (February 2026)

**All intelligence tiers through I8 are implemented and tested:**

- **I1 Technical Indicators** — 17 plugins with real incremental compute_next() (141x performance boost), including Supertrend and GARCH volatility
- **I2 Composite Indicators** — Crossovers, slopes, distances via `src/intelligence/composites/`
- **I3 Market Structure** — 3 plugins: swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure (regime + integrity)
- **I4 Context Classification** — 5 plugins: volatility regime (ATR percentile, BB width), trend regime (SMA alignment + I3 blending), momentum context (multi-oscillator scoring), GARCH(1,1) conditional volatility + regime, Kalman filter trend (filtered fair value, slope, uncertainty bands, 7 outputs)
- **I5 Pattern Detection** — 5 plugins: RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence, trend confluence (6-signal aggregation)
- **I6 Smart Money Concepts** — 6 plugins: BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime classification
- **I6 Cross-Timeframe Confluence** — 1 plugin: trend/structure/regime/pattern alignment scoring across 1m/5m/15m/1h
- **I7 Trading Setups** — 5 plugins: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion
- **I7 Signal Aggregation** — 4 components: signal_ledger (TimescaleDB hypertable), rules-based aggregator, lifecycle tracker, position sizer
- **I7 Signal Orchestrator** — Live service subscribing to intelligence streams, calling all 5 I7 plugins, aggregating results, publishing to `signals:SYMBOL:TF:aggregated`
- **I8 AI Narrative** — `AINarrativeService` consumes `signals:SYMBOL:TF:aggregated`, calls local Ollama (qwen3:8b), publishes human-readable narratives to `narratives:SYMBOL:TF` stream + hash cache
- **Data Collection Efficiency** — Provisional bars at :00 (tick-derived OHLCV), authoritative correction via reqHistoricalData at :05; `source` field distinguishes bar types
- **Intelligence Processor Service** — Full I1→I3→I4→I5→SMC→I6→I7 pipeline in `services/intelligence_processor_service.py`
- **Foundation Hardening** — Shared utils (find_peaks/find_troughs), temporal metadata, continuous confidence scores
- **Tier 2 Refactor** — Split calculations.py (2,383→62 lines) and redis_streams_manager.py (1,938→229 lines) into mixins
- **Dead Code Removed** — ~7,500 lines across three cleanup rounds
- **Dependency Upgrades** — pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, LangChain 1.2, OpenAI SDK 2.20, Next.js 15.5
- **Dashboard** — Next.js 15 / React 19 trading dashboard with price hero, indicator grid, pattern/structure/context/smart money/confluence panels

**Infrastructure Status: PRODUCTION READY**
**Test Status: 366 unit tests passing, 0 ruff errors**

---

## Development Priorities

### Priority 1: Dashboard Narrative Panel
**Wire the I8 narrative stream to the trading dashboard**

- SSE endpoint for `narratives:SYMBOL:TF` stream
- Dashboard React component showing live AI-generated trade narratives
- Real-time update whenever a new signal fires and narrative is generated
- This closes the human feedback loop on I7 signal quality

### Priority 2: More Regime & Market Identification
**Probabilistic models for regime detection and trend estimation**

- Chart patterns (double top/bottom, head & shoulders, triangles/wedges)
- See `docs/plans/future-indicators-backlog.md` for full specs

### Priority 3: I7 Phase 2 — More Setup Plugins
**Expand signal coverage with 9 additional setup plugins**

- VWAP Deviation Setup (mean reversion on ES/NQ)
- Momentum Breakout Setup (ROC spike + volume confirmation)
- Supply/Demand Zone Setup
- Gap Analysis Setup (session open trades)
- See `docs/roadmap/MASTER_ROADMAP.md` Phase 4 for full list

### Priority 4: ML Scoring Model Calibration
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
| **I5** | Pattern detection: 4 plugins (RSI divergence, Bollinger squeeze, volume divergence, confluence) | Complete |
| **FH** | Foundation hardening: shared utils, temporal metadata, continuous scores | Complete |
| **SMC** | Smart money concepts: 6 plugins (BOS/CHoCH, FVG, OB, liq sweeps, BOCPD, HMM) | Complete |
| **I6** | Cross-timeframe confluence: trend/structure/regime/pattern alignment scoring | Complete |
| **Cleanup** | ~7,500 lines dead code removed across three rounds | Complete |
| **Deps** | Full dependency upgrade (pandas 3.0, redis 7.1, LangGraph 1.0, etc.) | Complete |
| **I1-ext** | Supertrend indicator + GARCH(1,1) volatility forecast + TrendConfluence pattern | Complete |
| **I7-P1** | I7 Phase 1: 5 trading setup plugins | Complete |
| **I7-P1.5** | I7 Phase 1.5: signal aggregation components (ledger, aggregator, lifecycle, sizer) | Complete |
| **I7-Orch** | Signal Orchestrator Service: live signal collection running (port 9112) | Complete |
| **DataEff** | Data collection efficiency: provisional bars at :00, authoritative correction at :05 | Complete |
| **I8** | AI Narrative Service: Ollama qwen3:8b narratives from aggregated signals (port 9113) | Complete |
| **I4-Kalman** | ctx_KalmanTrend: 1D Kalman filter, 7 outputs, optional GARCH-adaptive R, 9 tests | Complete |

---

## Architecture Quick Reference

**Plugin Totals:** 42 registered (17 I1 indicators + 5 I5 patterns + 3 I3 structure + 5 I4 context + 6 SMC smart money + 1 I6 confluence + 5 I7 setups)
**Services:** hf-tws-daemon, indicator-processor, enhanced-processor, timeframe-builder, intelligence-processor, signal-orchestrator (:9112), ai-narrative (:9113)
**Stack:** Python 3.13, FastAPI 0.129, Redis 7.1/DragonflyDB, TimescaleDB, LangGraph 1.0, Ollama
**Dashboard:** Next.js 15.5 / React 19 / Tailwind v4

---

**Detailed Architecture:** [CLAUDE.md](../CLAUDE.md)
**Intelligence Tiers:** [docs/architecture/intelligence-tiers.md](architecture/intelligence-tiers.md)
**Plugin Framework:** [docs/architecture/plugin-registry-and-dag-execution.md](architecture/plugin-registry-and-dag-execution.md)
**Roadmap:** [docs/roadmap/MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md)
**Future Indicators:** [docs/plans/future-indicators-backlog.md](plans/future-indicators-backlog.md)
