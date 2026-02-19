# IndicAgent Platform Status

> **Last Updated:** 2026-02-19
> **Version:** 4.4.0
> **Phase:** I1-I8 Pipeline Complete

---

## Current State Summary

**Infrastructure:** Production-ready
**Intelligence Pipeline:** Fully operational (I1 → I7)
**Test Coverage:** 357 unit tests passing, 0 lint errors
**Data Collection:** Active (ES, NQ, RTY + 11 more contracts)

---

## System Health

| Component | Status | Version | Health Endpoint |
|-----------|--------|---------|-----------------|
| HF TWS Daemon | RUNNING | 2.1.0 | N/A |
| Indicator Processor | RUNNING | 3.2.0 | :9109/health |
| Enhanced Processor | RUNNING | 1.0.0 | :9109/health |
| Timeframe Builder | RUNNING | 2.0.0 | :9110/health |
| Intelligence Processor | RUNNING | 2.5.0 | N/A |
| Signal Orchestrator | RUNNING | 1.0.0 | :9112/health |
| AI Narrative Service | RUNNING | 1.0.0 | :9113/health |
| Backend API | RUNNING | 4.1.0 | :8000/health |
| Dashboard | RUNNING | 1.5.0 | http://localhost:3000 |

---

## Intelligence Tiers

| Tier | Name | Plugins | Status | Details |
|------|------|---------|--------|---------|
| I1 | Technical Indicators | 17 | COMPLETE | [Reference](reference/plugins/i1-indicators.md) |
| I2 | Composite Indicators | — | COMPLETE | Built-in (crossovers, slopes) |
| I3 | Market Structure | 3 | COMPLETE | [Reference](reference/plugins/i3-structure.md) |
| I4 | Context Classification | 4 | COMPLETE | [Reference](reference/plugins/i4-context.md) |
| I5 | Pattern Detection | 5 | COMPLETE | [Reference](reference/plugins/i5-patterns.md) |
| I6 | Smart Money Concepts | 6 | COMPLETE | [Reference](reference/plugins/i6-smart-money.md) |
| I6 | Cross-Timeframe Confluence | 1 | COMPLETE | [Reference](reference/plugins/i6-smart-money.md) |
| I7 | Trading Setups | 5 | PHASE_1_COMPLETE | [Reference](reference/plugins/i7-trading.md) |
| I7 | Signal Aggregation | 4 components | RUNNING | Signal Orchestrator service wired |
| I8 | AI Intelligence | 1 service | WORKING | Ollama qwen3:8b, narratives stream |

**Total Plugins:** 41 registered

---

## Data Infrastructure

**Hot Tier:** DragonflyDB (Redis protocol) - <1ms latency
**Warm Tier:** Redis Streams - Real-time processing
**Cold Tier:** TimescaleDB - Historical analysis

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

**Python:** 3.11+
**Key Dependencies:** pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0
**Infrastructure:** Docker (TimescaleDB, DragonflyDB, Ollama)
**Frontend:** Next.js 15.5, React 19

**Local LLMs (Ollama):** 5 models available at http://localhost:11434
- **Default:** `qwen3:8b` (5.2 GB, thinking mode)
- See [Intelligence Tiers](concepts/intelligence-tiers.md#i8) for full model list

---

## Next Steps

See [MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md) for detailed priorities.

**Immediate Priority:** Dashboard Narrative Panel — wire `narratives:SYMBOL:TF` stream to SSE endpoint and dashboard React component

---

## Recent Changes

### 2026-02-19 (v4.4.0)
- COMPLETE I8 AI Narrative Service: Ollama qwen3:8b narratives from `signals:aggregated`
- COMPLETE Data Collection Efficiency: provisional bars (tick_derived at :00) + authoritative correction (histData at :05)
- ADD `narratives:SYMBOL:TF` stream (maxlen=100) + `narrative:SYMBOL:TF:latest` hash cache (90s TTL)
- ADD `source` field to bar messages: `tick_derived` vs `authoritative`
- ADD xack-in-finally PEL safety pattern to AINarrativeService and SignalOrchestrator
- TEST +48 new unit tests (309 → 357 total)

### 2026-02-18 (v4.3.0)
- FIX `is_num` NaN/Inf vulnerability (math.isfinite guard)
- FIX VWAP session reset on date boundary + add SD bands (±1σ, ±2σ)
- FIX TrendRegime consumes upstream sma_20/sma_50 from features
- PERF Vectorize find_peaks/find_troughs with numpy (~50-100x speedup)
- REFACTOR ADX deduplication — single-pass computation (remove _seed_state)
- REFACTOR SupportResistance uses shared vectorized peak detection
- ADD Supertrend indicator (ATR-based binary trend direction, I1)
- ADD GARCH(1,1) volatility forecast (conditional vol + regime, I4)
- ADD TrendConfluence pattern (6-signal trend aggregation, I5)
- TEST +51 new unit tests (258 → 309 total)

### 2026-02-17 (v4.2.0)
- COMPLETE I7 Phase 1.5: Signal aggregation components (aggregator, ledger, lifecycle, sizer)
- ADD 45 new tests for signal aggregation
- UPDATE Consolidated planning docs into MASTER_ROADMAP.md
- UPDATE Restructured documentation with STATUS.md as single source of truth

### 2026-02-16 (v4.1.0)
- COMPLETE I7 Phase 1: 5 trading setup plugins
- ADD signal.v1 schema with SSE wiring
- ADD 35 new tests

### 2026-02-15 (v4.0.0)
- COMPLETE I6 Smart Money: BOCPD changepoint + HMM regime classification
- ADD Cross-timeframe confluence plugin

---

**Note:** This is the canonical reference for current state. All other docs link here instead of duplicating version/status info.
