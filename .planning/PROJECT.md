# IndicAgent

## What This Is

IndicAgent is a real-time futures trading intelligence platform that ingests live market data from Interactive Brokers, runs it through a 7-tier plugin pipeline (I1–I8) producing technical indicators, market structure analysis, pattern detection, smart money concepts, and AI-generated signal narratives. It is a derived intelligence system — everything it produces is derived from price, volume, and time. The platform publishes all intelligence to a Redis Streams bus and exposes it via FastAPI with SSE.

This milestone refactors the architecture toward an institutional-grade unified data bus: typed structured events replacing flat string streams, a persistent feature store for ML training, service consolidation, and a predictive ML scoring model layered on top of the reactive signal pipeline.

## Core Value

Every intelligence output — indicator, pattern, signal, narrative — flows through one canonical typed bus that both internal and external consumers can trust.

## Requirements

### Validated

(Already built and working in production)

- ✓ Real-time IBKR tick ingestion → 1m bar aggregation — existing
- ✓ Multi-timeframe bar aggregation (1m → 5m/15m/1h/4h/1d) — existing
- ✓ 23 technical indicator plugins (I1 tier) with incremental compute — existing
- ✓ Market structure analysis: I3 (swing/S&R/trend), I4 (volatility/trend/momentum/GARCH/Kalman), I5 (patterns/divergence/squeeze), SMC (BOS/CHoCH/FVG/order blocks), I6 (confluence) — existing
- ✓ Signal generation: 9 I7 setup plugins with aggregation → signal_ledger — existing
- ✓ Signal lifecycle tracking with P&L calculation — existing
- ✓ AI narrative generation via Ollama/LangGraph (I8) — existing
- ✓ FastAPI with SSE streaming + historical query endpoints — existing
- ✓ Plugin circuit breaker + Redis state persistence — existing
- ✓ Historical backfill pipeline (IBKR → TimescaleDB) — existing
- ✓ Plugin tier registry as single source of truth with startup validation — existing
- ✓ GARCH/Kalman quality gates on MeanReversion, VWAPDeviation, SqueezeExpansion (I7) — Phase 0, 2026-02-22

### Active

(Building this milestone)

- [ ] `IntelligenceEvent` Pydantic schema — typed structured events replacing flat string k/v stream messages, tiered JSONB (i1/i3/i4/i5/smc/i6), versioned
- [ ] `intelligence_features` TimescaleDB hypertable — tiered JSONB columns, GIN indexes, compressed after 7 days, no retention (keep for seasonal ML)
- [ ] Feature Writer Service — async Redis consumer group persisting `IntelligenceEvent` to `intelligence_features`
- [ ] Service consolidation — deprecate `intelligence_processor_service.py`, single canonical pipeline via `market_analysis_service.py`
- [ ] Plugin state persistence — `get_state()`/`restore_state()` on all stateful plugins, checkpointed every 60 bars
- [ ] Historical backfill running — DB populated with 365 days, 2,700+ signals in `signal_ledger` for ML calibration
- [ ] Historical query API — query `intelligence_features` by symbol/timeframe/date range
- [ ] ML scoring model — predictive layer consuming `intelligence_features` to score forward probability of signal success
- [ ] Auth layer — JWT (humans/Vercel) + API keys (machines) via single FastAPI `Depends(verify_auth)`
- [ ] External access — Cloudflare Tunnel → HTTPS for Vercel frontend

### Out of Scope

- Order execution / trade management — intelligence only, no execution
- Multi-platform intelligence systems (fundamentals, sentiment, news) — documented as future goals below
- Portfolio management or position sizing — out of scope for intelligence platform
- Real-time latency SLAs / co-location infrastructure — not a HFT system

## Future Goals

These are documented to inform current design decisions (bus must be extensible) but are not in this milestone's roadmap.

**Multi-Platform Intelligence Architecture:**

The unified data bus is designed to support multiple independent intelligence platforms that share the same bus infrastructure. Each platform would have its own plugin pipeline, feature store partition, and AI agents for organizing and interpreting its domain's data — but all publish to and consume from the same typed event bus.

Candidate future platforms:
- **Fundamentals Platform** — quarterly reports, balance sheets, cash flows, income statements; derived signals about company financial health
- **Sentiment Platform** — options flow, put/call ratios, social sentiment, analyst ratings
- **News Platform** — earnings announcements, macro events, geopolitical developments; event-driven signals
- **Cross-Platform AI Agents** — agents that synthesize signals across all platforms (e.g., "technicals + fundamentals agree → high conviction")

Design implication: `IntelligenceEvent` schema and `intelligence_features` table must support a `platform` dimension from day one.

## Context

- **Infrastructure**: Ollama (:11434, 5 local models), PostgreSQL/TimescaleDB (:5432), DragonflyDB Redis-compatible (:6379), IBKR TWS on Windows LAN (10.0.0.33)
- **Current contracts**: H6 (March 2026 expiry) — defined in `src/config/settings.py`
- **Data flow**: flat k/v strings currently flow through Redis Streams; this milestone replaces them with `IntelligenceEvent` typed events
- **Existing design doc**: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` — detailed decisions already made
- **Test baseline**: 551 unit tests passing at milestone start (v4.9.2)

## Constraints

- **Stack**: Python 3.13, FastAPI, DragonflyDB, TimescaleDB, asyncpg — no stack changes
- **Backwards compatibility**: Stream key names unchanged during migration; `IntelligenceEvent` publisher must be drop-in for existing consumers until migration complete
- **No retention on intelligence_features**: Data kept indefinitely for seasonal ML analysis
- **IBKR dependency**: Live data requires TWS connection on Windows LAN; historical backfill also via IBKR

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Canonical pipeline: `market_analysis_service.py` only | `intelligence_processor_service.py` duplicates pipeline logic; single service eliminates confusion | — Pending |
| `IntelligenceEvent` replaces flat k/v strings | Typed schema enables structured queries, ML feature extraction, external API contracts | — Pending |
| `intelligence_features` hypertable, no retention | Intelligence data has seasonal patterns; retain all for ML; TimescaleDB compression reduces storage cost | — Pending |
| Feature Writer Service as separate process | Decouples persistence from pipeline hot path; Redis consumer group enables fan-out | — Pending |
| Plugin state: Redis hash `plugin_state:{symbol}:{tf}:{plugin_name}` | Survives service restarts; 7-day TTL prevents stale state; 60-bar checkpoint interval | ✓ Implemented in plugin_state_manager.py |
| Auth: single `Depends(verify_auth)` for JWT + API keys | One entry point for both human (Vercel) and machine (external apps) consumers | — Pending |
| `platform` dimension in IntelligenceEvent from day one | Multi-platform future requires bus to partition by platform; retrofitting is costly | — Pending |

---
*Last updated: 2026-02-22 after initialization*
