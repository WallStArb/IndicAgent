# IndicAgent Platform Status

> **Last Updated:** 2026-02-28
> **Version:** 5.6.0
> **Phase:** Phases 0–7 complete — 62 plugins, 781 tests; Phase 7 (CIS) complete

---

## Current State Summary

**Infrastructure:** Production-ready
**Intelligence Pipeline:** Fully operational (I1 → I8)
**Test Coverage:** 781 unit tests passing, 0 lint errors
**Data Collection:** Active (23 contracts across equity index, energy, metals, rates, FX, agriculture, crypto)

---

## System Health

| Service (systemd unit) | Port | Health |
|------------------------|------|--------|
| `indicagent-tws` — IBKR TWS daemon | — | — |
| `indicagent-indicator` — I1 indicators + multi-TF | 9109 | `/metrics` |
| `indicagent-market-analysis` — I3→I6 pipeline | 9114 | `/metrics` |
| `indicagent-signal-generator` — I7 setups + aggregation | 9112 | `/metrics` |
| `indicagent-signal-tracker` — signal lifecycle | 9115 | `/metrics` |
| `indicagent-ai-narrative` — Ollama I8 narratives | 9113 | `/metrics` |
| `indicagent-feature-writer` — Redis → intelligence_features | 9116 | `/metrics` |
| `indicagent-api` — FastAPI REST + SSE | 8000 | `/health` |
| Dashboard (dev) | 3000 | http://localhost:3000 |

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
| I7 | Trading Setups | 14 (9 original + 5 CIS) | COMPLETE (Phase 7: +5 CIS plugins, CIS aggregator, WeightUpdater) |
| I7 | Signal Aggregation | 4 components | RUNNING |
| I8 | AI Intelligence | 1 service | RUNNING (per-signal + group synthesis) |

**Total Plugins:** 62 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 I6 SMC + 1 I6 confluence + 14 I7)

### Known Issues

None.

---

## Development Priorities

### Priority 1: Phase 8 — ML Scoring Model / Dashboard Completion
- Requires 500+ signals in `signal_ledger` with P&L outcomes (~17 days collection)
- XGBoost/LightGBM on extracted features → pnl_r continuous target
- Dashboard: complete Phase 06-04 human verification (confirm all panels show live data)
- See `.planning/ROADMAP.md` for full roadmap

### Phase 7 status — COMPLETE
- ✅ 5 new I7 plugins: trad_CHoCHReversal, trad_FVGFill, trad_PatternCompletion, trad_DivergenceStack, trad_RegimeTransition
- ✅ CISScorer (6-bucket weighted scorer, replaces winner-pick)
- ✅ REGIME_ELIGIBILITY filter in aggregator
- ✅ WeightUpdater (sklearn LogisticRegression, migration 012)
- ✅ signal_ledger +4 CIS columns (migration 011)
- ✅ trade_framer: at_limit + at_pullback entry types

### Phase 6 status
- ✅ 06-01 through 06-03 complete
- ⏸ 06-04 skipped (human verification) — deferred to Phase 8

### Priority 2: ML Scoring Model (future)
- Requires 500+ signals in `signal_ledger` with P&L outcomes (~17 days collection)
- XGBoost/LightGBM on extracted features → pnl_r continuous target
- See `.planning/ROADMAP.md` for full roadmap

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
| **Phase 7 (CIS)** | Composite Intelligence Score: 5 new I7 plugins, CISScorer (6-bucket weighted), REGIME_ELIGIBILITY filter, WeightUpdater (sklearn LogisticRegression), signal_ledger +4 cols, trade_framer at_limit/at_pullback; 781 tests | Complete |

---

## Data Infrastructure

**Hot Tier:** DragonflyDB (Redis protocol) — <1ms latency
**Warm Tier:** Redis Streams — Real-time processing
**Cold Tier:** TimescaleDB — Historical analysis

**Stream Keys** (env-prefixed, e.g. `development:` in dev):
- Ticks: `ticks:SYMBOL:live`
- Indicators: `indicators:SYMBOL:TF`
- Intelligence (typed IntelligenceEvent): `intelligence:SYMBOL:TF`
- Signals: `signals:SYMBOL:TF:aggregated`
- Narratives (per-symbol): `narratives:SYMBOL:TF`
- Narratives (group synthesis): `narratives:group:GROUP_NAME`

See [Stream Schemas](reference/schemas/stream-schemas.md) for details.

---

## Instrumentation

**Active Contracts:** 23 futures (all H6/J6 front-month as of Feb 2026)
- **Equity Indices:** ES, NQ, RTY, YM
- **Energy:** CL, BZ, NG
- **Metals:** GC, SI, HG, PL
- **Rates:** ZN, ZF, ZB, ZT, SR1
- **Volatility:** VX
- **Agriculture:** ZS, ZC, ZW
- **FX:** 6E, 6J
- **Crypto:** BTC

**Timeframes:** 1m, 5m, 15m, 1h, 4h, 1d

---

## Development Environment

**Python:** 3.13
**Key Dependencies:** pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, LangChain 1.2
**Infrastructure:** DragonflyDB (Docker); PostgreSQL/TimescaleDB + Ollama (native)
**LLM Providers:** Ollama (local: qwen3:8b, phi4-mini:3.8b, etc.) + OpenRouter (cloud)
**Frontend:** Next.js 16.1, React 19.2, Tailwind v4.2

**Local LLMs (Ollama):** Available at http://localhost:11434
- **Default:** `qwen3:8b` (5.2 GB, thinking mode)
- See [Intelligence Tiers](concepts/intelligence-tiers.md#i8) for full model list

---

## Architecture Quick Reference

**Plugin Totals:** 62 registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 6 SMC + 1 I6 confluence + 14 I7) | 781 unit tests
**Services (systemd):** indicagent-tws, indicagent-indicator (:9109), indicagent-market-analysis (:9114), indicagent-signal-generator (:9112), indicagent-signal-tracker (:9115), indicagent-ai-narrative (:9113), indicagent-feature-writer (:9116), indicagent-api (:8000)
**Stack:** Python 3.13, FastAPI 0.129, DragonflyDB/Redis, TimescaleDB, LangGraph 1.0, Ollama + OpenRouter
**Dashboard:** Next.js 16.1 / React 19.2 / Tailwind v4.2

**Detailed Architecture:** [CLAUDE.md](for-ai-assistants/CLAUDE.md)
**Intelligence Tiers:** [docs/concepts/intelligence-tiers.md](concepts/intelligence-tiers.md)
**Plugin Framework:** [docs/architecture/plugin-registry-and-dag-execution.md](architecture/plugin-registry-and-dag-execution.md)
**Roadmap:** [docs/roadmap/MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md)

---

## Recent Changes

### 2026-02-28 (v5.6.0)
- COMPLETE Phase 7 — Composite Intelligence Score (CIS):
  - ADD 5 new I7 plugins: trad_CHoCHReversal, trad_FVGFill, trad_PatternCompletion, trad_DivergenceStack, trad_RegimeTransition
  - ADD CISScorer (6-bucket weighted scorer): trend 20% / momentum 20% / structure 15% / pattern 5% / institutional 25% / regime 15%
  - ADD REGIME_ELIGIBILITY filter in aggregator: trend plugins gate to regime 1/2, mean-reversion to regime 0; bypassed when hmm_regime_prob < 0.55 or duration < 3
  - ADD WeightUpdater (sklearn LogisticRegression) — adaptive weight learning from signal_ledger outcomes
  - ADD cis_weights table (migration 012), signal_ledger +4 CIS cols (migration 011)
  - ADD at_limit + at_pullback entry types to trade_framer
  - TEST +179 tests (602 → 781 total)

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
