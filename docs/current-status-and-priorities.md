# IndicAgent - Current Status & Development Priorities

**Version:** 3.0.0
**Last Updated:** 2026-02-15
**Status:** I1-I6 Complete, 33 Plugins, 178 Tests Passing

## Current Status: I1-I6 Intelligence Complete

### Completed Work (February 2026)

**All intelligence tiers through I6 are implemented and tested:**

- **I1 Technical Indicators** — 16 plugins with real incremental compute_next() (141x performance boost)
- **I2 Composite Indicators** — Crossovers, slopes, distances via `src/intelligence/composites/`
- **I3 Market Structure** — 3 plugins: swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure (regime + integrity)
- **I4 Context Classification** — 3 plugins: volatility regime (ATR percentile, BB width), trend regime (SMA alignment + I3 blending), momentum context (multi-oscillator scoring)
- **I5 Pattern Detection** — 4 plugins: RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence
- **I6 Smart Money Concepts** — 6 plugins: BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime classification
- **I6 Cross-Timeframe Confluence** — 1 plugin: trend/structure/regime/pattern alignment scoring across 1m/5m/15m/1h
- **Intelligence Processor Service** — Full I1→I3→I4→I5→SMC→I6 pipeline in `services/intelligence_processor_service.py`
- **Foundation Hardening** — Shared utils (find_peaks/find_troughs), temporal metadata, continuous confidence scores
- **Tier 2 Refactor** — Split calculations.py (2,383→62 lines) and redis_streams_manager.py (1,938→229 lines) into mixins
- **Dead Code Removed** — ~7,500 lines across three cleanup rounds
- **Dependency Upgrades** — pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, LangChain 1.2, OpenAI SDK 2.20, Next.js 15.5
- **Dashboard** — Next.js 15 / React 19 trading dashboard with price hero, indicator grid, pattern/structure/context/smart money/confluence panels

**Infrastructure Status: PRODUCTION READY**
**Test Status: 178 unit tests passing, 0 ruff errors**

---

## Development Priorities

### Priority 1: More Regime & Market Identification
**Probabilistic models for regime detection and volatility forecasting**

- GARCH Volatility — conditional volatility forecasting, vol-of-vol regime detection
- Kalman Filter Trend — latent-state trend estimation with adaptive noise filtering
- Chart patterns (double top/bottom, head & shoulders, triangles/wedges)

### Priority 2: I7 Trading Outputs
**Validated setups and actionable intelligence signals**

- Setup validation combining I6 confluence with entry/exit criteria
- Signal generation with confidence scoring and risk parameters
- Position sizing recommendations based on volatility regime and HMM state

### Priority 3: I8 AI Intelligence
**LLM-powered market narratives and insights**

- OpenRouter integration for cost-optimized LLM access
- Pattern interpretation and market narrative generation
- Human-readable intelligence summaries
- Cost controls with micro-batching and caching

### Priority 4: Additional I1 Indicators
**Expand indicator coverage per backlog**

- Batch 2: Parabolic SAR, SuperTrend, Chaikin Money Flow
- Batch 3: Stochastic RSI, Aroon, Chandelier Exit
- See `docs/plans/future-indicators-backlog.md` for full backlog

---

## Completed Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **LG-1** | LangGraph event-driven workflows, circuit breakers | Complete |
| **CQ-1** | Code quality: 1,323 lint fixes, formatting | Complete |
| **PR-2** | Production: test runner, incremental_manager, parallel services, SSE | Complete |
| **PI-1** | 16 indicator plugins with hybrid processing | Complete |
| **T2** | Tier 2 refactor: calculations.py + redis_streams_manager.py split into mixins | Complete |
| **I5** | Pattern detection: 4 plugins (RSI divergence, Bollinger squeeze, volume divergence, confluence) | Complete |
| **I3** | Market structure: 3 plugins (swing detector, support/resistance, trend structure) | Complete |
| **I4** | Context classification: 3 plugins (volatility regime, trend regime, momentum context) | Complete |
| **FH** | Foundation hardening: shared utils, temporal metadata, continuous scores | Complete |
| **SMC** | Smart money concepts: 6 plugins (BOS/CHoCH, FVG, OB, liq sweeps, BOCPD, HMM) | Complete |
| **I6** | Cross-timeframe confluence: trend/structure/regime/pattern alignment scoring | Complete |
| **Cleanup** | ~7,500 lines dead code removed across three rounds | Complete |
| **Deps** | Full dependency upgrade (pandas 3.0, redis 7.1, LangGraph 1.0, etc.) | Complete |

---

## Architecture Quick Reference

**Plugin Totals:** 33 registered (16 indicators + 17 patterns/structure/context/smart_money)
**Services:** hf-tws-daemon, indicator-processor, timeframe-builder, intelligence-processor
**Stack:** Python 3.13, FastAPI 0.129, Redis 7.1/DragonflyDB, TimescaleDB, LangGraph 1.0
**Dashboard:** Next.js 15.5 / React 19 / Tailwind v4

---

**Detailed Architecture:** [CLAUDE.md](../CLAUDE.md)
**Intelligence Tiers:** [docs/architecture/intelligence-tiers.md](architecture/intelligence-tiers.md)
**Plugin Framework:** [docs/architecture/plugin-registry-and-dag-execution.md](architecture/plugin-registry-and-dag-execution.md)
**Future Indicators:** [docs/plans/future-indicators-backlog.md](plans/future-indicators-backlog.md)
